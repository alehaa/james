# This file is part of James CI.
#
# James CI is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# James CI is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with James CI. If not, see <http://www.gnu.org/licenses/>.
#
#
# Copyright (C)
#   2017 Alexander Haase <ahaase@alexhaase.de>
#

import contextlib
import os
import time
import types
import yaml

from .job import Job
from .job_base import JobBase


class Pipeline(JobBase):
    """
    This class helps managing pipelines. It imports the pipeline's configuration
    and handles all neccessary error checks.
    """

    CONFIG_FILE = 'pipeline.yml'
    """
    Name of the pipeline's configuration file.
    """

    def __init__(self, data, project_wd, pipeline_id=None, with_meta=True):
        """
        .. warning::
          If `with_meta` is set to :py:data:`False`, this constructor does
          **NOT** initialize all attributes. It shall not be called directly.
          Use :py:meth:`new` for creating a new pipeline or :py:meth:`load` to
          load existing ones instead.


        :param dict data: Dict containing the pipeline's configuration. May be
          imported from either the repository's `.james-ci.yml` or a pipeline's
          `pipeline.yml` file.
        :param str project_wd: The working directory of the project, i.e. the
          path where all pipelines of a specific project will be stored.
        :param None,int pipeline_id: The ID of this pipeline.
        :param bool with_meta: Whether to load metadata from `data`. Only
          :py:meth:`new` should set this parameter to :py:data:`False` for
          creating a new :py:class:`~.Pipeline`.

        :raises ImportError: Failed to import a job.
        """
        # Initialize the parent class, which imports the common keys for
        # pipelines and jobs.
        super().__init__(data)

        # Import the pipeline's specific data.
        self._id = pipeline_id
        self._pwd = project_wd

        # Import the pipeline's jobs. First, the list of defined stages will be
        # loaded, then the jobs will be imported. If importing any job fails,
        # an ImportError exception with the job's name will be raised, so a
        # meaningful error message may be printed by the exception handler.
        self._stages = data.get('stages')
        self._jobs = dict()
        for name, conf in data['jobs'].items():
            try:
                self._jobs[name] = Job(conf, self, with_meta=with_meta)
            except Exception as e:
                raise ImportError("failed to load job '{}'".format(name)) from e

        # If enabled, import the meta-data for this pipeline from the provided
        # data dictionary. There won't be any specialized checks for the avail-
        # ability of any of the required fields, but an exception will be thrown
        # if a key is not available.
        if with_meta:
            self._created = data['meta']['created']
            self._contact = data['meta']['contact']
            self._revision = data['meta']['revision']

    @classmethod
    def new(cls, data, project_wd, revision, contact):
        """
        Create a new pipeline.


        :param dict data: Dict containing the pipeline's configuration. Should
          be imported from the repository's `.james-ci.yml` file.
        :param str project_wd: The working directory of the project, i.e. the
          path where all pipelines of a specific project will be stored.
        :param str revision: Revision to checkout for the pipeline.
        :param str contact: E-Mail address of the committer (e.g. to send him a
          message about the pipeline's status after all jobs run).
        :return: The new pipeline.
        :rtype: Pipeline
        """
        # Create a new pipeline with the provided data. The meta-data will not
        # be initialized, as the in-repository configuration file doesn't
        # contain any meta-data.
        pipeline = cls(data, project_wd, with_meta=False)

        # Initialize the meta-data. The created time of the pipeline will be set
        # to the current UNIX timestamp, the revision and contact data to the
        # value of the passed parameters.
        pipeline._created = int(time.time())
        pipeline._contact = contact
        pipeline._revision = revision

        # Return the freshly created pipeline. Caution: it's hot!
        return pipeline

    @classmethod
    def load(cls, project_wd, pipeline_id):
        """
        Load an existing pipeline from the pipeline's working directory.


        :param str project_wd: The working directory of the project, i.e. the
          path where all pipelines of a specific project will be stored.
        :param int pipeline_id: The ID of the pipeline to load.
        :return: The loaded pipeline.
        :rtype: Pipeline
        """
        # Get the path for the pipeline's configuration file.
        path = os.path.join(cls.__pwd(project_wd, pipeline_id), cls.CONFIG_FILE)

        # Open the configuration file for the given pipeline and parse its
        # contents. Its values will be used to construct a new Pipeline object.
        return cls(yaml.load(open(path)), project_wd, pipeline_id=pipeline_id)

    def dump(self):
        """
        Dump the configuration as dict.


        :return: The configuration of this pipeline.
        :rtype: dict
        """
        # Get the dictionary generated by the parent class. This dictionary will
        # be updated with the pipeline-specific configuration.
        ret = super().dump()
        ret['meta'] = {
            'created': self._created,
            'contact': self._contact,
            'revision': self._revision
        }
        if self._stages:
            ret['stages'] = self._stages
        ret['jobs'] = {name: job.dump() for name, job in self._jobs.items()}
        return ret

    def __get_new_id(self):
        """
        :return: A new ID for this pipeline.
        :rtype: int
        """
        # If the working directory for all pipelines already exists, get the
        # next available ID depending on the contents of this directory. The ID
        # to be returned will be the maximum ID found in the directory
        # incremented by one.
        if os.path.exists(self._pwd):
            pipelines = os.listdir(self._pwd)
            if pipelines:
                return max(map(int, pipelines)) + 1

        # If the working directory for pipelines doesn't exist yet, or is empty,
        # return the first available ID 1.
        return 1

    def __assign_new_id(self):
        """
        Assign a new ID for this pipeline.

        .. note::
          This method will not only assign the new ID, but also makes a new
          working directory for this pipeline to reserve this ID. to avoid two
          pipelines with the same ID when more than one process is running at
          the moment.


        :raises OSError: Failed to assign a new ID to this pipeline due race
          conditions with other processes.
        """
        # Try up to three times to assign a new ID to this pipeline. This needs
        # to be done to catch race conditions, where another process may have
        # assigned the ID to its pipeline while this one tries to assign the
        # same ID.
        for i in range(3):
            with contextlib.suppress(FileExistsError):
                pipeline_id = self.__get_new_id()
                os.makedirs(self.__pwd(self._pwd, pipeline_id))
                self._id = pipeline_id
                return

        # If all tries have failed to assign an ID for this pipeline, raise an
        # exception.
        raise OSError('other processes block ID assignment')

    def save(self):
        """
        Save the pipeline configuration to the configuration file in the
        pipeline's working directory.
        """
        # If no ID is assigned to this pipeline yet, require a new ID for this
        # pipeline first.
        if self._id is None:
            self.__assign_new_id()

        # Dump the configuration of this pipeline as YAML in a configuration
        # file placed inside the pipeline's working directory.
        yaml.dump(self.dump(),
                  open(os.path.join(self.pwd, self.CONFIG_FILE), 'w'),
                  default_flow_style=False)

    @property
    def contact(self):
        """
        :return: The pipeline's contact email address.
        :rtype: str
        """
        return self._contact

    @property
    def created(self):
        """
        :return: The pipeline's creation time as UNIX timestamp.
        :rtype: int
        """
        return self._created

    @property
    def id():
        """
        :return: The pipeline's id.
        :rtype: None, int
        """
        return self._id

    @property
    def jobs(self):
        """
        .. note::
          The dictionary of jobs is read-only to ensure jobs can't be added nor
          removed. However, the job itself may be modified.


        :return: The pipeline's jobs.
        :rtype: types.MappingProxyType(dict)
        """
        return types.MappingProxyType(self._jobs)

    @staticmethod
    def __pwd(project_wd, pipeline_id):
        """
        :param str project_wd: The working directory of the project, i.e. the
          path where all pipelines of a specific project will be stored.
        :param int pipeline_id: The ID of the pipeline.
        :return: The pipeline's working directory.
        :rtype: str
        """
        return os.path.join(project_wd, str(pipeline_id))

    @property
    def pwd(self):
        """
        .. note::
          If no ID is assigned to the pipeline yet, the working directory of the
          pipeline doesn't exist yet, thus the working directory of this
          pipeline will be :py:data:`None`.


        :return: The pipeline's working directory.
        :rtype: str
        """
        return self.__pwd(self._pwd, self._id) if self._id else None

    @property
    def revision(self):
        """
        :return: The pipeline's revision to checkout.
        :rtype: str
        """
        return self._revision

    @property
    def stages(self):
        """
        :return: The pipeline's stages.
        :rtype: None, tuple
        """
        return tuple(self._stages) if self._stages else None
