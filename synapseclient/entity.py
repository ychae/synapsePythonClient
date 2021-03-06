"""
******
Entity
******

The Entity class is the base class for all entities, including Project, Folder
and File, Link, as well as deprecated entity types such as Data, Study, Summary,
etc.

Entities are dictionary-like objects in which both object and dictionary
notation (entity.foo or entity['foo']) can be used interchangeably.

Imports::

    from synapseclient import Project, Folder, File, Link

.. autoclass:: synapseclient.entity.Entity

~~~~~~~
Project
~~~~~~~

.. autoclass:: synapseclient.entity.Project

~~~~~~
Folder
~~~~~~

.. autoclass:: synapseclient.entity.Folder

~~~~
File
~~~~

.. autoclass:: synapseclient.entity.File

Changing File Names
-------------------

A Synapse File Entity has a name separate from the name of the actual file
it represents. When a file is uploaded to Synapse, its filename is fixed,
even though the name of the entity can be changed at any time. Synapse provides
a way to change this filename and the content-type of the file for future downloads
by creating a new version of the file with a modified copy of itself.  This can be 
done with the synapseutils.copy.changeFileMetaData function.

>>> import synapseutils
>>> e = syn.get(synid)
>>> print(os.path.basename(e.path))  ## prints, e.g., "my_file.txt"
>>> e = synapseutils.changeFileMetaData(syn, e, "my_newname_file.txt")

Setting *fileNameOverride* will **not** change the name of a copy of the
file that's already downloaded into your local cache. Either rename the
local copy manually or remove it from the cache and re-download.:

>>> syn.cache.remove(e.dataFileHandleId)
>>> e = syn.get(e)
>>> print(os.path.basename(e.path))  ## prints "my_newname_file.txt"

~~~~
Link
~~~~

.. autoclass:: synapseclient.entity.Link

~~~~~~~~~~~~
Table Schema
~~~~~~~~~~~~

.. autoclass:: synapseclient.table.Schema


~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Properties and annotations, implementation details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In Synapse, entities have both properties and annotations. Properties are used
by the system, whereas annotations are completely user defined. In the Python
client, we try to present this situation as a normal object, with one set of
properties.

Printing an entity will show the division between properties and annotations.::

    print(entity)

Under the covers, an Entity object has two dictionaries, one for properties and one
for annotations. These two namespaces are distinct, so there is a possibility of
collisions. It is recommended to avoid defining annotations with names that collide
with properties, but this is not enforced.::

    ## don't do this!
    entity.properties['description'] = 'One thing'
    entity.annotations['description'] = 'A different thing'

In case of conflict, properties will take precedence.::

    print(entity.description)
    #> One thing

Some additional ambiguity is entailed in the use of dot notation. Entity
objects have their own internal properties which are not persisted to Synapse.
As in all Python objects, these properties are held in object.__dict__. For
example, this dictionary holds the keys 'properties' and 'annotations' whose
values are both dictionaries themselves.

The rule, for either getting or setting is: first look in the object then look
in properties, then look in annotations. If the key is not found in any of
these three, a get results in a ``KeyError`` and a set results in a new
annotation being created. Thus, the following results in a new annotation that
will be persisted in Synapse::

    entity.foo = 'bar'

To create an object member variable, which will *not* be persisted in
Synapse, this unfortunate notation is required::

    entity.__dict__['foo'] = 'bar'

As mentioned previously, name collisions are entirely possible.
Keys in the three namespaces can be referred to unambiguously like so::

    entity.__dict__['key']

    entity.properties.key
    entity.properties['key']

    entity.annotations.key
    entity.annotations['key']

Most of the time, users should be able to ignore these distinctions and treat
Entities like normal Python objects. End users should never need to manipulate
items in __dict__.

See also:

- :py:mod:`synapseclient.annotations`

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.utils import python_2_unicode_compatible
from builtins import str
import six

import collections
import itertools
if six.PY2:
    from StringIO import StringIO
else:
    from io import StringIO

from synapseclient.dict_object import DictObject
import synapseclient.utils as utils
from synapseclient.utils import id_of, itersubclasses
from synapseclient.exceptions import *
import os


class Versionable(object):
    """An entity for which Synapse will store a version history."""

    _synapse_entity_type = 'org.sagebionetworks.repo.model.Versionable'
    _property_keys = ['versionNumber', 'versionLabel', 'versionComment', 'versionUrl', 'versions']


## TODO: inherit from UserDict.DictMixin?
##       http://docs.python.org/2/library/userdict.html#UserDict.DictMixin

## Alternate implementations include:
## - a naming convention to tag object members
## - keeping a list of 'transient' variables (the object members)
## - giving up on the dot notation (implemented in Entity2.py in commit e441fcf5a6963118bcf2b5286c67fc66c004f2b5 in the entity_object branch)
## - giving up on hiding the difference between properties and annotations

@python_2_unicode_compatible
class Entity(collections.MutableMapping):
    """
    A Synapse entity is an object that has metadata, access control, and
    potentially a file. It can represent data, source code, or a folder
    that contains other entities.

    Entities should typically be created using the constructors for specific
    subclasses such as Project, Folder or File.
    """

    _synapse_entity_type = 'org.sagebionetworks.repo.model.Entity'
    _property_keys = ['id', 'name', 'description', 'parentId',
                     'entityType', 'concreteType',
                     'uri', 'etag', 'annotations', 'accessControlList',
                     'createdOn', 'createdBy', 'modifiedOn', 'modifiedBy']
    _local_keys = []

    @classmethod
    def create(cls, properties=None, annotations=None, local_state=None):
        """
        Create an Entity or a subclass given dictionaries of properties
        and annotations, as might be received from the Synapse Repository.

        :param properties:  A map of Synapse properties

            If 'concreteType' is defined in properties, we create the proper subclass
            of Entity. If not, give back the type whose constructor was called:

            If passed an Entity as input, create a new Entity using the input
            entity as a prototype.

        :param annotations: A map of user defined annotations
        :param local_state: Allow local state to be given.
                            This state information is not persisted
                            in the Synapse Repository.
        """

        # Create a new Entity using an existing Entity as a prototype
        if isinstance(properties, Entity):
            if annotations is None: annotations = {}
            if local_state is None: local_state = {}
            annotations.update(properties.annotations)
            local_state.update(properties.local_state())
            properties = properties.properties
            if 'id' in properties: del properties['id']

        if cls==Entity and 'concreteType' in properties and properties['concreteType'] in _entity_type_to_class:
            cls = _entity_type_to_class[properties['concreteType']]
        return cls(properties=properties, annotations=annotations, local_state=local_state)

    @classmethod
    def getURI(self, id):
        return '/entity/%s' %id


    def __new__(typ, *args, **kwargs):
        obj = object.__new__(typ)

        # Make really sure that properties and annotations exist before
        # any object methods get invoked. This is important because the
        # dot operator magic methods have been overridden and depend on
        # properties and annotations existing.
        obj.__dict__['properties'] = DictObject()
        obj.__dict__['annotations'] = DictObject()
        return obj


    def __init__(self, properties=None, annotations=None, local_state=None, parent=None, **kwargs):

        if properties:
            if isinstance(properties, collections.Mapping):
                if 'annotations' in properties and isinstance(properties['annotations'], collections.Mapping):
                    annotations.update(properties['annotations'])
                    del properties['annotations']
                self.__dict__['properties'].update(properties)
            else:
                raise SynapseMalformedEntityError('Unknown argument type: properties is a %s' % str(type(properties)))

        if annotations:
            if isinstance(annotations, collections.Mapping):
                self.__dict__['annotations'].update(annotations)
            elif isinstance(annotations, str):
                self.properties['annotations'] = annotations
            else:
                raise SynapseMalformedEntityError('Unknown argument type: annotations is a %s' % str(type(annotations)))

        if local_state:
            if isinstance(local_state, collections.Mapping):
                self.local_state(local_state)
            else:
                raise SynapseMalformedEntityError('Unknown argument type: local_state is a %s' % str(type(local_state)))

        for key in self.__class__._local_keys:
            if key not in self.__dict__:
                self.__dict__[key] = None

        # Extract parentId from parent
        if 'parentId' not in kwargs:
            if parent:
                try:
                    kwargs['parentId'] = id_of(parent)
                except Exception:
                    if isinstance(parent, Entity) and 'id' not in parent:
                        raise SynapseMalformedEntityError("Couldn't find 'id' of parent.  Has it been stored in Synapse?")
                    else:
                        raise SynapseMalformedEntityError("Couldn't find 'id' of parent.")

        # Note: that this will work properly if derived classes declare their
        # internal state variable *before* invoking super(...).__init__(...)
        for key, value in six.iteritems(kwargs):
            self.__setitem__(key, value)

        if 'concreteType' not in self:
            self['concreteType'] = self.__class__._synapse_entity_type

        ## Only project can be top-level. All other entity types require parentId
        ## don't enforce this for generic Entity
        if 'parentId' not in self and not isinstance(self, Project) and not type(self)==Entity:
            raise SynapseMalformedEntityError("Entities of type %s must have a parentId." % type(self))



    def postURI(self):
        return '/entity'

    def putURI(self):
        return '/entity/%s' %self.id

    def deleteURI(self, versionNumber=None):
        if versionNumber:
            return '/entity/%s/version/%s' % (self.id,versionNumber)
        else:
            return '/entity/%s' %self.id



    def local_state(self, state=None):
        """
        Set or get the object's internal state, excluding properties, or annotations.

        :param state: A dictionary
        """
        if state:
            for key,value in six.iteritems(state):
                if key not in ['annotations','properties']:
                    self.__dict__[key] = value
        result = {}
        for key,value in six.iteritems(self.__dict__):
            if key not in ['annotations','properties'] and not key.startswith('__'):
                result[key] = value
        return result


    def __setattr__(self, key, value):
        return self.__setitem__(key, value)


    def __setitem__(self, key, value):
        if key in self.__dict__:
            # If we assign like so:
            #   entity.annotations = {'foo';123, 'bar':'bat'}
            # Wrap the dictionary in a DictObject so we can
            # later do:
            #   entity.annotations.foo = 'bar'
            if (key=='annotations' or key=='properties') and not isinstance(value, DictObject):
                value = DictObject(value)
            self.__dict__[key] = value
        elif key in self.__class__._property_keys:
            self.properties[key] = value
        else:
            self.annotations[key] = value

    ## TODO: def __delattr__

    def __getattr__(self, key):
        # Note: that __getattr__ is only called after an attempt to
        # look the key up in the object's dictionary has failed.
        if key in self.__dict__:
            return self.__dict__[key]
        elif key in self.properties:
            return self.properties[key]
        elif key in self.annotations:
            return self.annotations[key]
        else:
            ## Note that hasattr in Python2 is more permissive than Python3
            ## about what exceptions it catches. In Python3, hasattr catches
            ## only AttributeError
            raise AttributeError(key)


    def __getitem__(self, key):
        if key in self.__dict__:
            return self.__dict__[key]
        elif key in self.properties:
            return self.properties[key]
        elif key in self.annotations:
            return self.annotations[key]
        else:
            raise KeyError(key)


    def __delitem__(self, key):
        if key in self.properties:
            del self.properties[key]
        elif key in self.annotations:
            del self.annotations[key]


    def __iter__(self):
        return iter(self.keys())


    def __len__(self):
        return len(self.keys())


    ## TODO shouldn't these include local_state as well? -jcb
    def keys(self):
        """Returns a set of property and annotation keys"""
        return set(self.properties.keys()) | set(self.annotations.keys())

    def has_key(self, key):
        """Is the given key a property or annotation?"""

        return key in self.properties or key in self.annotations

    def __str__(self):
        f = StringIO()

        f.write('%s: %s (%s)\n' % (self.__class__.__name__, self.properties.get('name', 'None'), self['id'] if 'id' in self else '-',))

        def write_kvps(dictionary, key_filter=None):
            for key in sorted(dictionary.keys()):
                if (not key_filter) or key_filter(key):
                    f.write('  ')
                    f.write(str(key))
                    f.write('=')
                    f.write(str(dictionary[key]))
                    f.write('\n')

        write_kvps(self.__dict__, lambda key: not (key in ['properties', 'annotations'] or key.startswith('__')))

        f.write('properties:\n')
        write_kvps(self.properties)

        f.write('annotations:\n')
        write_kvps(self.annotations)

        return f.getvalue()

    def __repr__(self):
        """Returns an eval-able representation of the Entity."""

        f = StringIO()
        f.write(self.__class__.__name__)
        f.write("(")
        f.write(", ".join(
            {"%s=%s" % (str(key), value.__repr__(),) for key, value in
                itertools.chain(
                    list([k_v for k_v in six.iteritems(self.__dict__) if not (k_v[0] in ['properties', 'annotations'] or k_v[0].startswith('__'))]),
                    six.iteritems(self.properties),
                    six.iteritems(self.annotations))}))
        f.write(")")
        return f.getvalue()


class Project(Entity):
    """
    Represents a project in Synapse.

    Projects in Synapse must be uniquely named. Trying to create a project with
    a name that's already taken, say 'My project', will result in an error

    ::

        project = Project('Foobarbat project')
        project = syn.store(project)
    """

    _synapse_entity_type = 'org.sagebionetworks.repo.model.Project'

    def __init__(self, name=None, properties=None, annotations=None, local_state=None, **kwargs):
        if name: kwargs['name'] = name
        super(Project, self).__init__(concreteType=Project._synapse_entity_type, properties=properties,
                                      annotations=annotations, local_state=local_state, **kwargs)


class Folder(Entity):
    """
    Represents a folder in Synapse.

    Folders must have a name and a parent and can optionally have annotations.

    ::

        folder = Folder('my data', parent=project)
        folder = syn.store(Folder)
    """

    _synapse_entity_type = 'org.sagebionetworks.repo.model.Folder'

    def __init__(self, name=None, parent=None, properties=None, annotations=None, local_state=None, **kwargs):
        if name: kwargs['name'] = name
        super(Folder, self).__init__(concreteType=Folder._synapse_entity_type, properties=properties,
                                     annotations=annotations, local_state=local_state, parent=parent, **kwargs)

class Link(Entity):
    """
    Represents a link in Synapse.

    Links must have a target ID and a parent. When you do synapseclient.Synapse.get on a Link object,
    the Link object is returned. If the target is desired, specify followLink=True in synapseclient.Synapse.get.

    :param targetVersion:       Version of the file you want to create a link for

    ::

        link = Link('targetID', parent=folder)
        link = syn.store(link)
    """
    _property_keys = Entity._property_keys+ ['linksTo','linksToClassName']
    _local_keys = Entity._local_keys
    _synapse_entity_type = 'org.sagebionetworks.repo.model.Link'

    def __init__(self, targetId=None, targetVersion=None, parent=None, properties=None, annotations=None, local_state=None, **kwargs):
        if targetId is not None:
            kwargs['linksTo'] = dict(targetId=targetId, targetVersionNumber=targetVersion)
        elif properties is not None and 'linksTo' in properties:
            pass
        else:
            raise SynapseMalformedEntityError("Must provide a target id")
        super(Link, self).__init__(concreteType=Link._synapse_entity_type, properties=properties,
                                     annotations=annotations, local_state=local_state, parent=parent, **kwargs)


class File(Entity, Versionable):
    """
    Represents a file in Synapse.

    When a File object is stored, the associated local file or its URL will be
    stored in Synapse. A File must have a path (or URL) and a parent.

    :param path:             Location to be represented by this File
    :param name:             Name of the file in Synapse, not to be confused with the name within the path
    :param parent:           Project or Folder where this File is stored
    :param synapseStore:     Whether the File should be uploaded or if only the path should be stored.
                             Defaults to True (file should be uploaded)
    :param contentType:      Manually specify Content-type header, for example "application/png" or "application/json; charset=UTF-8"
    :param dataFileHandleId: Defining an existing dataFileHandleId will use the existing dataFileHandleId
                             The creator of the file must also be the owner of the dataFileHandleId to have permission to store the file
    ::

        data = File('/path/to/file/data.xyz', parent=folder)
        data = syn.store(data)
    """

    _property_keys = Entity._property_keys + Versionable._property_keys + ['dataFileHandleId']
    _local_keys = Entity._local_keys + ['path', 'cacheDir', 'files', 'synapseStore', 'externalURL', 'md5', 'fileSize', 'contentType']
    _synapse_entity_type = 'org.sagebionetworks.repo.model.FileEntity'

    ## TODO: File(path="/path/to/file", synapseStore=True, parentId="syn101")
    def __init__(self, path=None, parent=None, synapseStore=True, properties=None,
                 annotations=None, local_state=None, **kwargs):
        if path and 'name' not in kwargs:
            kwargs['name'] = utils.guess_file_name(path)
        if path and 'dataFileHandleId' in kwargs:
            raise ValueError('Please only specify path or dataFileHandleId')
        self.__dict__['path'] = path
        if path:
            cacheDir, basename = os.path.split(path)
            self.__dict__['cacheDir'] = cacheDir
            self.__dict__['files'] = [basename]
        else:
            self.__dict__['cacheDir'] = None
            self.__dict__['files'] = []
        self.__dict__['synapseStore'] = synapseStore
        super(File, self).__init__(concreteType=File._synapse_entity_type, properties=properties,
                                   annotations=annotations, local_state=local_state, parent=parent, **kwargs)
        # if not synapseStore:
        #     self.__setitem__('concreteType', 'org.sagebionetworks.repo.model.file.ExternalFileHandle')


# Create a mapping from Synapse class (as a string) to the equivalent Python class.
_entity_type_to_class = {}
for cls in itersubclasses(Entity):
    _entity_type_to_class[cls._synapse_entity_type] = cls


def split_entity_namespaces(entity):
    """
    Given a plain dictionary or an Entity object,
    splits the object into properties, annotations and local state.
    A dictionary will be processed as a specific type of Entity
    if it has a valid 'concreteType' field,
    otherwise it is treated as a generic Entity.

    :returns: a 3-tuple (properties, annotations, local_state).
    """
    if isinstance(entity, Entity):
        # Defensive programming: return copies
        return (entity.properties.copy(), entity.annotations.copy(), entity.local_state())

    if not isinstance(entity, collections.Mapping):
        raise SynapseMalformedEntityError("Can't split a %s object." % entity.__class__.__name__)

    if 'concreteType' in entity and entity['concreteType'] in _entity_type_to_class:
        entity_class = _entity_type_to_class[entity['concreteType']]
    else:
        entity_class = Entity

    properties = DictObject()
    annotations = DictObject()
    local_state = DictObject()

    property_keys = entity_class._property_keys
    local_keys = entity_class._local_keys
    for key, value in six.iteritems(entity):
        if key in property_keys:
            properties[key] = value
        elif key in local_keys:
            local_state[key] = value
        else:
            annotations[key] = value

    return (properties, annotations, local_state)



ENTITY_TYPES = [
    'org.sagebionetworks.repo.model.FileEntity',
    'org.sagebionetworks.repo.model.Folder',
    'org.sagebionetworks.repo.model.Link',
    'org.sagebionetworks.repo.model.Project',
    'org.sagebionetworks.repo.model.table.TableEntity'
]

def is_synapse_entity(entity):
    if isinstance(entity, Entity):
        return True
    if isinstance(entity, collections.Mapping):
        return entity.get('concreteType', None) in ENTITY_TYPES
    return False


def is_versionable(entity):
    """Return True if the given entity's concreteType is one that is Versionable."""

    if isinstance(entity, Versionable):
        return True

    try:
        if 'concreteType' in entity and entity['concreteType'] in _entity_type_to_class:
            entity_class = _entity_type_to_class[entity['concreteType']]
            return issubclass(entity_class, Versionable)
    except TypeError:
        pass

    return False


def is_container(entity):
    """Test if an entity is a container (ie, a Project or a Folder)"""
    if 'concreteType' in entity:
        concreteType = entity['concreteType']
    elif isinstance(entity, collections.Mapping):
        prefix = utils.extract_prefix(entity.keys())
        if prefix+'concreteType' in entity:
            concreteType = entity[prefix+'concreteType'][0]
        elif prefix+'nodeType' in entity:
            return entity[prefix+'nodeType'] in ['project', 'folder']
        else:
            return False
    else:
        return False
    return concreteType in (Project._synapse_entity_type, Folder._synapse_entity_type)

