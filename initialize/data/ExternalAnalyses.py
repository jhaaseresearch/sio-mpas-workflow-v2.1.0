#!/usr/bin/env python3

'''
 (C) Copyright 2023 UCAR

 This software is licensed under the terms of the Apache Licence Version 2.0
 which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
'''

from copy import deepcopy

from initialize.config.Component import Component
from initialize.config.Config import Config
from initialize.config.Resource import Resource
from initialize.config.Task import TaskLookup
from initialize.config.TaskFamily import placeholdertask

from initialize.data.StateEnsemble import StateEnsemble

from initialize.framework.HPC import HPC

class ExternalAnalyses(Component):
  defaults = 'scenarios/defaults/externalanalyses.yaml'
  workDir = 'ExternalAnalyses'
  requiredVariables = {
    ## resource:
    # used to select from among available options (e.g., see defaults)
    # must be in quotes
    # e.g., "GFS.RDA", "GFS.NCEPFTP", "GFS.PANDAC",  "GFS.SIO", "ERA5.RDA"
    'resource': str,
  }

  def __init__(self, config:Config, hpc:HPC, meshes:dict):
    super().__init__(config)
    self.meshes = meshes

    ###################
    # derived variables
    ###################
    resourceName = 'externalanalyses__resource'
    resource = self['resource']
    self._set(resourceName, resource)
    self._cshVars.append(resourceName)

    # WorkDir is where external analysis files are linked/downloaded, e.g., in grib format
    self.WorkDir = self.workDir+'/'+resource+'/{{thisValidDate}}'

    for meshTyp, mesh in meshes.items():
      nCells = str(mesh.nCells)
      # 'ExternalAnalysesDir'+meshTyp is where external analyses converted to MPAS meshes are
      # created and/or stored
      self._set('ExternalAnalysesDir'+meshTyp, self.workDir+'/'+mesh.name+'/{{thisValidDate}}')
      self._cshVars.append('ExternalAnalysesDir'+meshTyp)

      for (key, typ) in [
       ['directory', str],
       ['filePrefix', str],
       ['PrepareExternalAnalysisTasks', list],
       ['Vtable', str],
       ['UngribPrefix', str],
      ]:
        value = self.extractResource(('resources', resource, mesh.name), key, typ)

        if key == 'PrepareExternalAnalysisTasks':
          # push back cylc mini-workflow variables
          values = [task.replace('{{mesh}}',mesh.name) for task in value]

          # first add variable as a list of tasks
          variable = key+meshTyp
          self._set(variable, values)

          # then add as a joined string with dependencies between subtasks (" => ")
          # e.g.,
          # variable: PrepareExternalAnalysisTasksOuter becomes PrepareExternalAnalysisOuter
          # value: [a, b] becomes "a => b"
          variable = variable.replace('Tasks','')
          value = " => ".join(values)
          self._set(variable, value)
          continue

        else:
          # auto-generated csh variables
          variable = 'externalanalyses__'+key+meshTyp
          if key in ['Vtable','UngribPrefix']:
            if meshTyp == 'Outer':
              variable = 'externalanalyses__'+key
            else:
              continue

          if key == 'filePrefix' and isinstance(value, str):
            value = value.replace('{{nCells}}', nCells)

          self._set(variable, value)
          self._cshVars.append(variable)

    # Use external analysis for sea surface updating
    variable = 'PrepareSeaSurfaceUpdate'
    self._set(variable, self['PrepareExternalAnalysisOuter'])

    ########################
    # tasks and dependencies
    ########################
    self.__getRetry = self.extractResourceOrDie(('resources', resource), 'job.GetAnalysisFrom.retry', str)

    attr = {
      'seconds': {'def': 1200},
      'retry': {'def': '2*PT30S'},
      # currently UngribExternalAnalysis has to be on Cheyenne, because ungrib.exe is built there
      # TODO: build ungrib.exe on casper, remove Critical directives below, deferring to
      #       SingleBatch inheritance
      'queue': {'def': hpc['CriticalQueue']},
      'account': {'def': hpc['CriticalAccount']},
    }
    ungribjob = Resource(self._conf, attr, ('job', 'ungrib'))
    self.__ungribtask = TaskLookup[hpc.system](ungribjob)

    #########
    # outputs
    #########
    self.outputs = {}
    self.outputs['state'] = {}
    for meshTyp, mesh in meshes.items():
      self.outputs['state'][meshTyp] = StateEnsemble(mesh)
      self.outputs['state'][meshTyp].append({
        'directory': self['ExternalAnalysesDir'+meshTyp],
        'prefix': self['externalanalyses__filePrefix'+meshTyp],
      })

  def export(self, dtOffsets:list=[0]):

    # only once for each mesh
    meshTypes = []
    meshNames = []
    for meshTyp, mesh in self.meshes.items():
      if mesh.name not in meshNames:
        meshNames.append(mesh.name)
        meshTypes.append(meshTyp)

    subqueues = []
    prevTaskNames = {}
    zeroHR = '-0hr'
    for dt in dtOffsets:
      dtStr = str(dt)
      dtLen = '-'+dtStr+'hr'
      dt_work_Args = '"'+dtStr+'" "'+self.WorkDir+'"'
      taskNames = {}

      # GDAS FTP
      base = 'GetGDASAnalysisFromFTP'
      queue = 'GetExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh
    execution time limit = PT45M
    execution retry delays = '''+self.__getRetry]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]

      # GFS RDA
      base = 'GetGFSAnalysisFromRDA'
      queue = 'GetExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+dt_work_Args+'''
    execution time limit = PT20M
    execution retry delays = '''+self.__getRetry]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]

      # GFS FTP
      base = 'GetGFSAnalysisFromFTP'
      queue = 'GetExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+dt_work_Args+'''
    execution time limit = PT20M
    execution retry delays = '''+self.__getRetry]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]
      
      # ERA5 RDA
      base = 'GetERA5AnalysisFromRDA'
      queue = 'GetExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+dt_work_Args+'''
    execution time limit = PT20M
    execution retry delays = '''+self.__getRetry]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]

      # ungrib
      base = 'UngribExternalAnalysis'
      queue = 'UngribExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+dt_work_Args+'''
'''+self.__ungribtask.job()+self.__ungribtask.directives()]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]
      # ERA5 RDA
      base = 'UngribERA5ExternalAnalysis'
      queue = 'UngribExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        taskNames[base] = base+dtLen
        self._tasks += ['''
  [['''+taskNames[base]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+dt_work_Args+'''
'''+self.__ungribtask.job()+self.__ungribtask.directives()]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]

      # ready (not part of subqueue, order does not matter)
      base = 'ExternalAnalysisReady__'
# TODO: use 'finished' tag like other tasks
#      self._dependencies += ['''
#        '''+base+''' => '''+self.tf.finished]
      if base in self['PrepareExternalAnalysisOuter']:
        taskName = base+dtLen
        self._tasks += ['''
  [['''+taskName+''']]
    inherit = '''+self.tf.group+','+placeholdertask]

        # generic 0hr task name for external classes/tasks to grab
        if dt == 0:
          self._tasks += ['''
  [['''+base+''']]
    inherit = '''+base+zeroHR]

      # link (convert)
      base = 'LinkExternalAnalysis'
      queue = 'LinkExternalAnalyses'
      if base in self['PrepareExternalAnalysisOuter']:
        subqueues.append(queue)
        for meshTyp, meshName in zip(meshTypes, meshNames):
          taskNames[(base, meshName)] = base+'-'+meshName+dtLen
          args = [
            dt,
            self['ExternalAnalysesDir'+meshTyp],
            self['externalanalyses__directory'+meshTyp],
            self['externalanalyses__filePrefix'+meshTyp],
          ]
          linkArgs = ' '.join(['"'+str(a)+'"' for a in args])

          self._tasks += ['''
  [['''+taskNames[(base, meshName)]+''']]
    inherit = '''+queue+''', SingleBatch
    script = $origin/bin/'''+base+'''.csh '''+linkArgs+'''
    execution time limit = PT90S
    execution retry delays = 5*PT30S
    [[[events]]]
      submission timeout = PT1M''']

          # generic 0hr task name for external classes/tasks to grab
          if dt == 0:
            self._tasks += ['''
  [['''+base+'''-'''+meshName+''']]
    inherit = '''+base+'''-'''+meshName+zeroHR]


      # for all above, make task[t] depend on task[t-dt]
      for key, t_taskName in taskNames.items():
        if key in prevTaskNames:

          # special catch-all succeed string needed due to 0hr naming below
          if dtOffsets[0] == 0 and dtOffsets.index(dt) == 1:
            success = ':succeed-all'
          else:
            success = ''

          self._dependencies += ['''
    '''+prevTaskNames[key]+success+''' => '''+t_taskName]

      prevTaskNames = deepcopy(taskNames)

    # only 1 task per subqueue to avoid cross-cycle errors
    for queue in set(subqueues):
      self._tasks += ['''
  [['''+queue+''']]
    inherit = '''+self.tf.group]

      self._queues += ['''
    [[['''+queue+''']]]
      members = '''+queue+'''
      limit = 1''']

    ###########################
    # update tasks/dependencies
    ###########################
    self._dependencies = self.tf.updateDependencies(self._dependencies)
    self._tasks = self.tf.updateTasks(self._tasks, self._dependencies)

    # export all
    super().export()
