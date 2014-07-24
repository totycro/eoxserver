#-------------------------------------------------------------------------------
#
# Project: EOxServer <http://eoxserver.org>
# Authors: Fabian Schindler <fabian.schindler@eox.at>
#          Stephan Meissl <stephan.meissl@eox.at>
#          Stephan Krause <stephan.krause@eox.at>
#
#-------------------------------------------------------------------------------
# Copyright (C) 2011 EOX IT Services GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
# copies of the Software, and to permit persons to whom the Software is 
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies of this Software or works derived from this Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#-------------------------------------------------------------------------------

import logging
from itertools import chain

from django.core.exceptions import ValidationError
from django.contrib.gis.db import models
from django.utils.timezone import now

from eoxserver.core import models as base
from eoxserver.contrib import gdal, osr
from eoxserver.backends import models as backends
from eoxserver.resources.coverages.util import (
    detect_circular_reference, collect_eo_metadata, is_same_grid
)


logger = logging.getLogger(__name__)


#===============================================================================
# Helpers
#===============================================================================

def iscoverage(eo_object):
    """ Helper to check whether an EOObject is a coverage. """
    return issubclass(eo_object.real_type, Coverage)


def iscollection(eo_object):
    """ Helper to check whether an EOObject is a collection. """
    return issubclass(eo_object.real_type, Collection)


#===============================================================================
# Metadata classes
#===============================================================================

class Projection(models.Model):
    """ Model for elaborate projection definitions. The `definition` is valid 
        for a given `format`. The `spatial_reference` property returns an
        osr.SpatialReference for this Projection.
    """

    name = models.CharField(max_length=64, unique=True)
    format = models.CharField(max_length=16)

    definition = models.TextField()

    @property
    def spatial_reference(self):
        sr = osr.SpatialReference()

        # TODO: parse definition
        
        return sr

    def __unicode__(self):
        return self.name


class Extent(models.Model):
    """ Model mix-in for spatial objects which have a 2D Bounding Box expressed
        in a projection given either by a SRID or a whole `Projection` object.
    """

    min_x = models.FloatField()
    min_y = models.FloatField()
    max_x = models.FloatField()
    max_y = models.FloatField()
    srid = models.PositiveIntegerField(blank=True, null=True)
    projection = models.ForeignKey(Projection, blank=True, null=True)

    @property
    def spatial_reference(self):
        if self.srid is not None:
            sr = osr.SpatialReference()
            sr.ImportFromEPSG(self.srid)
            return sr
        else:
            return self.projection.spatial_reference
    
    @property
    def extent(self):
        """ Returns the extent as a 4-tuple. """
        return self.min_x, self.min_y, self.max_x, self.max_y

    @extent.setter
    def extent(self, value):
        """ Set the extent as a tuple. """
        self.min_x, self.min_y, self.max_x, self.max_y = value

    def clean(self):
        # make sure that neither both nor none of SRID or projections is set
        if self.projection is None and self.srid is None:
            raise ValidationError("No projection or srid given.")
        elif self.projection is not None and self.srid is not None:
            raise ValidationError(
                "Fields 'projection' and 'srid' are mutually exclusive."
            )

    class Meta:
        abstract = True


class EOMetadata(models.Model):
    """ Model mix-in for objects that have EO metadata (timespan and footprint)
        associated.
    """

    begin_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    footprint = models.MultiPolygonField(null=True, blank=True, srid=4326)
    
    objects = models.GeoManager()

    @property
    def extent_wgs84(self):
        if self.footprint is None: return None
        return self.footprint.extent

    @property
    def time_extent(self):
        return self.begin_time, self.end_time

    class Meta:
        abstract = True


class DataSource(backends.Dataset):
    pattern = models.CharField(max_length=32, null=False, blank=False)
    collection = models.ForeignKey("Collection")


#===============================================================================
# Base class EOObject
#===============================================================================


# registry to map the integer type IDs to the model types and vice-versa.
EO_OBJECT_TYPE_REGISTRY = {}


class EOObject(base.Castable, EOMetadata):
    """ Base class for EO objects. All EO objects share a pool of unique 
        `identifiers`.
    """

    identifier = models.CharField(max_length=256, unique=True, null=False, blank=False)

    # this field is required to be named 'real_content_type'
    real_content_type = models.PositiveSmallIntegerField()
    type_registry = EO_OBJECT_TYPE_REGISTRY


    objects = models.GeoManager()


    def __init__(self, *args, **kwargs):
        # TODO: encapsulate the change-tracking
        super(EOObject, self).__init__(*args, **kwargs)
        self._original_begin_time = self.begin_time
        self._original_end_time = self.end_time
        self._original_footprint = self.footprint


    def save(self, *args, **kwargs):
        super(EOObject, self).save(*args, **kwargs)

        # propagate changes of the EO Metadata up in the collection hierarchy
        if (self._original_begin_time != self.begin_time
            or self._original_end_time != self.end_time
            or self._original_footprint != self.footprint):

            for collection in self.collections.all():
                collection.update_eo_metadata()

        # set the new values for subsequent calls to `save()`
        self._original_begin_time = self.begin_time
        self._original_end_time = self.end_time
        self._original_footprint = self.footprint


    def __unicode__(self):
        return "%s (%s)" % (self.identifier, self.real_type._meta.verbose_name)


    class Meta:
        verbose_name = "EO Object"
        verbose_name_plural = "EO Objects"


class MetadataItem(models.Model):
    """ Model for generic key/value metadata item. a
        can be linked to either a storage or a package or none of both.
    """
    semantic = models.CharField(max_length=64,null=False,blank=False)
    value    = models.CharField(max_length=256,null=False, blank=False)
    eo_object = models.ForeignKey(EOObject,related_name="metadata_items")

    class Meta:
        verbose_name = "Metadata Item"
        verbose_name_plural = "Metadata Items"


#===============================================================================
# Identifier reservation
#===============================================================================

class ReservedIDManager(models.Manager):
    """ Model manager for `ReservedID` models for easier handling. Returns only
        `QuerySet`s that contain valid reservations.
    """
    def get_original_queryset(self):
        return super(ReservedIDManager, self).get_queryset()

    def get_queryset(self):
        Q = models.Q
        self.get_original_queryset().filter(
            Q(until__isnull=True) | Q(until__gt=now())
        )

    def cleanup_reservations(self):
        Q = models.Q
        self.get_original_queryset().filter(
            Q(until__isnull=False) | Q(until__lte=now())
        ).delete()

    def remove_reservation(self, identifier=None, request_id=None):
        if not identifier and not request_id:
            raise ValueError("Either identifier or request ID required")

        if identifier:
            model = self.get_original_queryset().get(identifier=identifier)
            if request_id and model.request_id != request_id:
                raise ValueError(
                    "Given request ID does not match the reservation."
                )
        else:
            model = self.get_original_queryset().get(request_id=request_id)
        model.delete()


class ReservedID(EOObject):
    """ Model to reserve a specific ID. The field `until` can be used to 
        specify the end of the reservation.
    """
    until = models.DateTimeField(null=True)
    request_id = models.CharField(max_length=256, null=True)

    objects = ReservedIDManager()


EO_OBJECT_TYPE_REGISTRY[0] = ReservedID

#===============================================================================
# RangeType structure
#===============================================================================


class NilValueSet(models.Model):
    """ Collection model for nil values.
    """

    name = models.CharField(max_length=512)
    data_type = models.PositiveIntegerField()

    def __init__(self, *args, **kwargs):
        super(NilValueSet, self).__init__(*args, **kwargs)
        self._cached_nil_values = None

    @property
    def values(self):
        return [nil_value.value for nil_value in self]

    def __unicode__(self):
        return "%s (%s)" % (self.name, gdal.GetDataTypeName(self.data_type))

    @property
    def cached_nil_values(self):
        if self._cached_nil_values is None:
            self._cached_nil_values = list(self.nil_values.all())
        return self._cached_nil_values

    def __iter__(self):
        return iter(self.cached_nil_values)

    def __len__(self):
        return len(self.cached_nil_values)

    def __getitem__(self, index):
        return self.cached_nil_values[index]

    class Meta:
        verbose_name = "Nil Value Set"


NIL_VALUE_CHOICES = (
    ("http://www.opengis.net/def/nil/OGC/0/inapplicable", "Inapplicable (There is no value)"),
    ("http://www.opengis.net/def/nil/OGC/0/missing", "Missing"),
    ("http://www.opengis.net/def/nil/OGC/0/template", "Template (The value will be available later)"),
    ("http://www.opengis.net/def/nil/OGC/0/unknown", "Unknown"),
    ("http://www.opengis.net/def/nil/OGC/0/withheld", "Withheld (The value is not divulged)"),
    ("http://www.opengis.net/def/nil/OGC/0/AboveDetectionRange", "Above detection range"),
    ("http://www.opengis.net/def/nil/OGC/0/BelowDetectionRange", "Below detection range")
)

class NilValue(models.Model):
    """ Single nil value contributing to a nil value set. 
    """

    raw_value = models.CharField(max_length=512, help_text="The string representation of the nil value.")
    reason = models.CharField(max_length=512, null=False, blank=False, choices=NIL_VALUE_CHOICES, help_text="A string identifier (commonly a URI or URL) for the reason of this nil value.")
    
    nil_value_set = models.ForeignKey(NilValueSet, related_name="nil_values")

    def __unicode__(self):
        return "%s (%s)" % (self.reason, self.raw_value)

    @property
    def value(self):
        """ Get the parsed python value from the saved value string.
        """
        dt = self.nil_value_set.data_type
        is_float   = False 
        is_complex = False

        if dt in gdal.GDT_INTEGRAL_TYPES :
            value =  int(self.raw_value)

        elif dt in gdal.GDT_FLOAT_TYPES :
            value =  float(self.raw_value)
            is_float = True 

        elif dt in gdal.GDT_INTEGRAL_COMPLEX_TYPES : 
            value =  complex(self.raw_value)
            is_complex = True

        elif dt in gdal.GDT_FLOAT_COMPLEX_TYPES : 
            value =  complex(self.raw_value)
            is_complex = True
            is_float = True 

        else:
            value = None

        # range check makes sense for integral values only 
        if not is_float : 

            limits = gdal.GDT_NUMERIC_LIMITS.get(dt)

            if limits and value is not None:
                def within(v, low, high):
                    return (v >= low and v <= high)

                error = ValueError(
                    "Stored value is out of the limits for the data type"
                )
                if not is_complex and not within(value, *limits) :
                    raise error
                elif is_complex:
                    if (not within(value.real, limits[0].real, limits[1].real)
                        or not within(value.real, limits[0].real, limits[1].real)):
                        raise error

        return value


    def clean(self):
        """ Check that the value can be parsed.
        """
        try:
            _ = self.value
        except Exception, e:
            raise ValidationError(str(e))

    class Meta:
        verbose_name = "Nil Value"


class RangeType(models.Model):
    """ Collection model for bands.
    """

    name = models.CharField(max_length=512, null=False, blank=False, unique=True)


    def __init__(self, *args, **kwargs):
        super(RangeType, self).__init__(*args, **kwargs)
        self._cached_bands = None

    def __unicode__(self):
        return self.name

    @property
    def cached_bands(self):
        if self._cached_bands is None:
            self._cached_bands = list(self.bands.all())
        return self._cached_bands

    def __iter__(self):
        return iter(self.cached_bands)

    def __len__(self):
        return len(self.cached_bands)

    def __getitem__(self, index):
        return self.cached_bands[index]

    class Meta:
        verbose_name = "Range Type"


class Band(models.Model):
    """ Model for storing band related metadata. 
    """

    index = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=512, null=False, blank=False)
    identifier = models.CharField(max_length=512, null=False, blank=False)
    description = models.TextField(null=True, blank=True)
    definition = models.CharField(max_length=512, null=True, blank=True)
    uom = models.CharField(max_length=64, null=False, blank=False)
    
    # GDAL specific
    data_type = models.PositiveIntegerField()
    color_interpretation = models.PositiveIntegerField(null=True, blank=True)

    range_type = models.ForeignKey(RangeType, related_name="bands", null=False, blank=False)
    nil_value_set = models.ForeignKey(NilValueSet, null=True, blank=True)
    

    def clean(self):
        nil_value_set = self.nil_value_set
        if nil_value_set and nil_value_set.data_type != self.data_type:
            raise ValidationError(
                "The data type of the band is not equal to the data type of "
                "its nil value set."
            )

    class Meta:
        ordering = ('index',)
        unique_together = (('index', 'range_type'), ('identifier', 'range_type'))


    def __unicode__(self):
        return "%s (%s)" % (self.name, gdal.GetDataTypeName(self.data_type))

    @property
    def allowed_values(self):
        return gdal.GDT_NUMERIC_LIMITS[self.data_type]

    @property
    def significant_figures(self):
        return gdal.GDT_SIGNIFICANT_FIGURES[self.data_type]


#===============================================================================
# Base classes for Coverages and Collections
#===============================================================================


class Coverage(EOObject, Extent, backends.Dataset):
    """ Common base model for all coverage types.
    """

    size_x = models.PositiveIntegerField()
    size_y = models.PositiveIntegerField()
    
    range_type = models.ForeignKey(RangeType)

    visible = models.BooleanField(default=False) # True means that the dataset is visible in the GetCapabilities response

    @property
    def size(self):
        return self.size_x, self.size_y

    @size.setter
    def size(self, value):
        self.size_x, self.size_y = value

    @property
    def resolution_x(self):
        return (self.max_x - self.min_x) / float(self.size_x)

    @property
    def resolution_y(self):
        return (self.max_y - self.min_y) / float(self.size_y)

    @property
    def resolution(self):
        return (self.resolution_x, self.resolution_y)

    objects = models.GeoManager()
    

class Collection(EOObject):
    """ Base model for all collections.
    """

    eo_objects = models.ManyToManyField(EOObject, through="EOObjectToCollectionThrough", related_name="collections")

    objects = models.GeoManager()

    def insert(self, eo_object, through=None):
        # TODO: a collection shall not contain itself!
        if self.pk == eo_object.pk:
            raise ValidationError("A collection cannot contain itself.")

        if through is None:
            # was not invoked by the through model, so create it first. 
            # insert will be invoked again in the `through.save()` method.
            logger.debug("Creating relation model for %s and %s." % (self, eo_object))
            through = EOObjectToCollectionThrough(eo_object=eo_object, collection=self)
            through.full_clean()
            through.save()
            return

        logger.debug("Inserting %s into %s." % (eo_object, self))

        # cast self to actual collection type
        self.cast().perform_insertion(eo_object, through)


    def perform_insertion(self, eo_object, through=None):
        """Interface method for collection insertions. If the insertion is not 
        possible, raise an exception.
        EO metadata collection needs to be done here as-well!
        """

        raise ValidationError("Collection %s cannot insert %s" % (str(self), str(eo_object)))


    def remove(self, eo_object, through=None):
        if through is None:
            EOObjectToCollectionThrough.objects.get(eo_object=eo_object, collection=self).delete()
            return

        logger.debug("Removing %s from %s." % (eo_object, self))
        
        # call actual remove method on actual collection type
        self.cast().perform_removal(eo_object)


    def perform_removal(self, eo_object):
        """ Interface method for collection removals. Update of EO-metadata needs
        to be performed here. Abortion of removal is not possible (atm).
        """
        raise NotImplementedError


    def update_eo_metadata(self):
        logger.debug("Updating EO Metadata for %s." % self)
        self.begin_time, self.end_time, self.footprint = collect_eo_metadata(self.eo_objects.all())
        self.full_clean()
        self.save()

    # containment methods

    def contains(self, eo_object, recursive=False):
        """ Check if an EO object is contained in a collection or subcollection,
        if `recursive` is set to `True`.
        """

        if not isinstance(eo_object, EOObject):
            raise ValueError("Expected EOObject.")

        if self.eo_objects.filter(pk=eo_object.pk).exists():
            return True

        if recursive:
            for collection in self.eo_objects.filter(collection__isnull=False):
                collection = collection.cast()
                if collection.contains(eo_object, recursive):
                    return True

        return False


    def __contains__(self, eo_object):
        """ Shorthand for non-recursive `contains()` method. """
        return self.contains(eo_object)

    def __iter__(self):
        return iter(self.eo_objects.all())

    def iter_cast(self, recursive=False):
        for eo_object in self.eo_objects.all():
            eo_object = eo_object.cast()
            yield eo_object
            if recursive and iscollection(eo_object):
                for item in eo_object.iter_cast(recursive):
                    yield item

    def __len__(self):
        if self.id == None:
            return 0
        return self.eo_objects.count()


class EOObjectToCollectionThrough(models.Model):
    """Relation of objects to collections. 
    Warning: do *not* use bulk methods of query sets of this collection, as it 
    will not invoke the correct `insert` and `remove` methods on the collection.
    """

    eo_object = models.ForeignKey(EOObject)
    collection = models.ForeignKey(Collection, related_name="coverages_set")

    objects = models.GeoManager()


    def __init__(self, *args, **kwargs):
        super(EOObjectToCollectionThrough, self).__init__(*args, **kwargs)
        try:
            self._original_eo_object = self.eo_object
        except: 
            self._original_eo_object = None

        try:
            self._original_collection = self.collection
        except:
            self._original_collection = None


    def save(self, *args, **kwargs):
        if (self._original_eo_object is not None 
            and self._original_collection is not None
            and (self._original_eo_object != self.eo_object
                 or self._original_collection != self.collection)):
            logger.debug("Relation has been altered!")
            self._original_collection.remove(self._original_eo_object, self)

        def getter(eo_object):
            return eo_object.collections.all()

        if detect_circular_reference(self.eo_object, self.collection, getter):
            raise ValidationError("Circular reference detected.")

        # perform the insertion
        # TODO: this is a bit buggy, as the insertion cannot be aborted this way
        # but if the insertion is *before* the save, then EO metadata collecting
        # still handles previously removed ones.
        self.collection.insert(self.eo_object, self)

        super(EOObjectToCollectionThrough, self).save(*args, **kwargs)

        self._original_eo_object = self.eo_object
        self._original_collection = self.collection


    def delete(self, *args, **kwargs):
        # TODO: pre-remove method? (maybe to cancel remove?)
        logger.debug("Deleting relation model between for %s and %s." % (self.collection, self.eo_object))
        result =  super(EOObjectToCollectionThrough, self).delete(*args, **kwargs)
        self.collection.remove(self.eo_object, self)
        return result


    class Meta:
        unique_together = (("eo_object", "collection"),)
        verbose_name = "EO Object to Collection Relation"
        verbose_name_plural = "EO Object to Collection Relations"


#===============================================================================
# Actual Coverage and Collections
#===============================================================================


class RectifiedDataset(Coverage):
    """ Coverage type using a rectified grid.
    """
    
    objects = models.GeoManager()
    
    class Meta:
        verbose_name = "Rectified Dataset"
        verbose_name_plural = "Rectified Datasets"

EO_OBJECT_TYPE_REGISTRY[10] = RectifiedDataset


class ReferenceableDataset(Coverage):
    """ Coverage type using a referenceable grid.
    """
    
    objects = models.GeoManager()
    
    class Meta:
        verbose_name = "Referenceable Dataset"
        verbose_name_plural = "Referenceable Datasets"

EO_OBJECT_TYPE_REGISTRY[11] = ReferenceableDataset


class RectifiedStitchedMosaic(Coverage, Collection):
    """ Collection type which can entail rectified datasets that share a common 
        range type and are on the same grid.
        NOTE: Geometry shall always be stored in the WGS84 lat/lon coordinates!
    """
    
    objects = models.GeoManager()
    
    class Meta:
        verbose_name = "Rectified Stitched Mosaic"
        verbose_name_plural = "Rectified Stitched Mosaics"

    def perform_insertion(self, eo_object, through=None):
        if eo_object.real_type != RectifiedDataset:
            raise ValidationError("In a %s only %s can be inserted." % (
                RectifiedStitchedMosaic._meta.verbose_name,
                RectifiedDataset._meta.verbose_name_plural
            ))

        rectified_dataset = eo_object.cast()
        if self.range_type != rectified_dataset.range_type:
            raise ValidationError(
                "Dataset '%s' has a different Range Type as the Rectified "
                "Stitched Mosaic '%s'." % (rectified_dataset, self.identifier)
            )

        if not is_same_grid((self, rectified_dataset)):
            raise ValidationError(
                "Dataset '%s' has not the same base grid as the Rectified "
                "Stitched Mosaic '%s'."  % (rectified_dataset, self.identifier)
            )

        self.begin_time, self.end_time, self.footprint = collect_eo_metadata(
            self.eo_objects.all(), insert=[eo_object]
        )
        # TODO: recalculate size and extent!
        self.full_clean()
        self.save()
        return

    def perform_removal(self, eo_object):
        self.begin_time, self.end_time, self.footprint = collect_eo_metadata(
            self.eo_objects.all(), exclude=[eo_object]
        )
        # TODO: recalculate size and extent!
        self.full_clean()
        self.save()
        return

EO_OBJECT_TYPE_REGISTRY[20] = RectifiedStitchedMosaic


class DatasetSeries(Collection):
    """ Collection type that can entail any type of EO object, even other 
        collections.
    """

    objects = models.GeoManager()

    class Meta:
        verbose_name = "Dataset Series"
        verbose_name_plural = "Dataset Series"


    def perform_insertion(self, eo_object, through=None):
        self.begin_time, self.end_time, self.footprint = collect_eo_metadata(
            self.eo_objects.all(), insert=[eo_object], bbox=True
        )
        self.full_clean()
        self.save()
        return

    def perform_removal(self, eo_object):
        self.begin_time, self.end_time, self.footprint = collect_eo_metadata(
            self.eo_objects.all(), exclude=[eo_object], bbox=True
        )
        self.full_clean()
        self.save()
        return

EO_OBJECT_TYPE_REGISTRY[30] = DatasetSeries

class VectorMask(models.Model): 
    """ Vector Mask metadata 
        NOTE: Geometry shall always be stored in the WGS84 lat/lon coordinates!
    """
    # EOP allowed mask types 
    CLOUD=1
    SNOW=2 
    QUALITY=3

    TYPE_CHOICES = ( 
        ( CLOUD, "CLOUD" ),
        ( SNOW, "SNOW" ),
        ( QUALITY,"QUALITY" ), 
    ) 

    type = models.PositiveSmallIntegerField( choices=TYPE_CHOICES,
                                            blank=False, null=False ) 
    subtype = models.CharField(max_length=64,blank=True, null=True)
    semantic = models.CharField(max_length=64,blank=True, null=True)
    geometry = models.MultiPolygonField(null=False, blank=False, srid=4326)
    objects = models.GeoManager()
    coverage = models.ForeignKey( Coverage, related_name='vector_masks' ) 
    
    def __unicode__(self):
        return "MASK{%s,%s%s}"%( self.coverage.identifier,
                dict(self.TYPE_CHOICES)[self.type] , 
                "" if self.subtype is None else "[%s]"%self.subtype )

    class Meta:
        verbose_name = "Vector Mask"
        verbose_name_plural = "Vector Masks"
