#!/usr/bin/env python3

from collections import OrderedDict

from initialize.applications.Members import Members

from initialize.config.Component import Component
from initialize.config.Config import Config
from initialize.config.Resource import Resource
from initialize.config.Task import TaskLookup
from initialize.config.TaskFamily import CylcTaskFamily

from initialize.data.Model import Model
from initialize.data.Observations import benchmarkObservations

from initialize.framework.HPC import HPC
from initialize.framework.Workflow import Workflow

class EnKF(Component):
  defaults = 'scenarios/defaults/enkf.yaml'

  requiredVariables = {
    ## solver [Required Parameter]
    # see classes derived from oops/src/oops/assimilation/LocalEnsembleSolver.h for all options
    'solver': [str,
      ['LETKF', 'GETKF'],
    ],
  }

  variablesWithDefaults = {
    ## observation localization parameters
    'localization dimension': ['3D', str, ['2D', '3D']],
    'horizontal localization method': ['Horizontal Gaspari-Cohn', str],
    'horizontal localization lengthscale': [1.2e6, float],
    # LETKF
    'vertical localization function': ['Gaspari Cohn', str],
    'vertical localization lengthscale': [6.e3, float],
    # GETKF
    #'vertical localization lengthscale': [5.0, float],

    ## observers
    # observation types assimilated in the enkf application
    # Abbreviations:
    #   clr == clear-sky
    #   cld == cloudy-sky
    # OPTIONS besides benchmarkObservations
    ## MW satellite-based
    # amsua-cld_aqua 
    # amsua-cld_metop-a 
    # amsua-cld_metop-b 
    # amsua-cld_n15 
    # amsua-cld_n18 
    # amsua-cld_n19 
    # mhs_n19 
    # mhs_n18 
    # mhs_metop-a 
    # mhs_metop-b 
    ## IR satellite-based
    # abi_g16 
    # ahi_himawari8 
    # abi-clr_g16 
    # ahi-clr_himawari8 
    # iasi_metop-a 
    # iasi_metop-b 
    # iasi_metop-c 
    'observers': [benchmarkObservations, list],

    ## nObsIndent
    # number of spaces to precede members of the 'observers' list in the JEDI YAML
    'nObsIndent': [2, int],

    ## biasCorrection
    # whether to use bias correction coefficients from VarBC or fixed
    # OPTIONS: False/True
    'biasCorrection': [False, bool],

    ## tropprsMethod
    # method for the tropopause pressure determination used in the
    # cloud detection filter for infrared observations
    # OPTIONS: thompson, wmo (currently the build code only works for thompson)
    'tropprsMethod': ['thompson', str, ['thompson', 'wmo']],

    ## maxIODAPoolSize
    # maximum number of IO pool members in IODA writer class
    # OPTIONS: 1 to NPE, default: 10
    #'maxIODAPoolSize': [10, int],
    'maxIODAPoolSize': [1, int],

    ## radianceThinningDistance
    # distance (km) used for the Gaussian Thinning filter for all radiance-based observations
    'radianceThinningDistance': [145.0, float],

    ## retainObsFeedback
    # whether to retain the observation feedback files (obs, geovals, ydiag)
    'retainObsFeedback': [True, bool],

    ## post
    # list of tasks for Post
    'post': [['verifyobs'], list]
  }

  def __init__(self,
    config:Config,
    hpc:HPC,
    meshes:dict,
    model:Model,
    members:Members,
    workflow:Workflow,
    parent:Component,
  ):
    super().__init__(config)

    NN = members.n
    assert NN > 1, ('members.n must be greater than 1')

    self.tf = parent.tf
    self.workDir = parent.workDir

    ###################
    # derived variables
    ###################
    solver = self['solver']
    if solver == 'GETKF':
      assert self['localization dimension'] == '3D', ('only 3D localization is supported for GETKF')
    self._set('AppName', 'enkf')
    self._set('appyaml', 'enkf.yaml')

    self._set('MeshList', ['EnKF'])
    self._set('nCellsList', [meshes['Outer'].nCells])
    self._set('StreamsFileList', [model['outerStreamsFile']])
    self._set('NamelistFileList', [model['outerNamelistFile']])
    self._set('localStaticFieldsFileList', [model['localStaticFieldsFileOuter']])

    # ensemble forecasts
    # EnKF uses online ensemble updating
    self._set('ensPbMemPrefix', workflow.MemPrefix)
    self._set('ensPbMemNDigits', workflow.MemNDigits)
    self._set('ensPbFilePrefix', 'mpasout')
    self._set('ensPbDir0', '{{ExperimentDirectory}}/CyclingFC/{{prevDateTime}}')
    # TODO: replace two lines above with these when forecast includes these attributes
    #self._set('ensPbFilePrefix', forecast.outputFilePrefix)
    #self._set('ensPbDir0', '{{ExperimentDirectory}}/'+forecast.WorkDir+'/{{prevDateTime}}')
    self._set('ensPbDir1', None)
    self._set('ensPbNMembers', NN)

    # TODO: this needs to be non-zero for EnKF workflows that use IAU, get value from forecast
    self._set('ensPbOffsetHR', 0)

    self._cshVars = list(self._vtable.keys())

    ########################
    # tasks and dependencies
    ########################
    # job resource settings

    attr = {
      'retry': {'t': str},
      'baseSeconds': {'t': int},
      'secondsPerMember': {'t': int},
      'nodes': {'t': int},
      'PEPerNode': {'t': int},
      'memory': {'def': '45GB', 't': str},
      'queue': {'def': hpc['CriticalQueue']},
      'account': {'def': hpc['CriticalAccount']},
      'email': {'def': True, 't': bool},
    }

    # EnKFObserver
    # r2observer = {{outerMesh}}.observer
    r2observer = meshes['Outer'].name
    r2observer += '.'+solver+'.observer'
    observerjob = Resource(self._conf, attr, ('job', r2observer))
    observerjob._set('seconds', observerjob['baseSeconds'] + observerjob['secondsPerMember'] * NN)
    observertask = TaskLookup[hpc.system](observerjob)

    # EnKF solver
    # r2solver = {{outerMesh}}.{{solver}}
    r2solver = meshes['Outer'].name
    r2solver += '.'+solver+'.solver'

    # add threads attribute
    attr['threads'] = {'def': 1, 't': int}

    solverjob = Resource(self._conf, attr, ('job', r2solver))
    solverjob._set('seconds', solverjob['baseSeconds'] + solverjob['secondsPerMember'] * NN)
    solvertask = TaskLookup[hpc.system](solverjob)

    self._set('solverThreads', solverjob.get('threads'))
    self._cshVars.append('solverThreads')

    args = [
      0,
      self.lower,
      self.workDir+'/{{thisCycleDate}}',
      workflow['CyclingWindowHR'],
    ]
    initArgs = ' '.join(['"'+str(a)+'"' for a in args])

    # 2 init phases
    if self['execute']:
      self._dependencies += ['''
        InitEnKF_0 => InitEnKF_1''']

      self._tasks += ['''
  ## enkf tasks
  [[InitEnKF_0]]
    inherit = '''+self.tf.init+''', SingleBatch
    script = $origin/bin/PrepJEDI.csh '''+initArgs+'''
    execution time limit = PT10M
    execution retry delays = '''+solverjob['retry']+'''

  [[InitEnKF_1]]
    inherit = '''+self.tf.init+''', SingleBatch
    script = $origin/bin/InitEnKF.csh
    execution time limit = PT10M
    execution retry delays = '''+solverjob['retry']+'''

  # clean
  [[CleanEnKFs]]
    inherit = '''+self.tf.clean+'''
    script = $origin/bin/CleanEnKF.csh

  [[EnKFObserver]]
    inherit = '''+self.tf.execute+''', BATCH
    script = $origin/bin/EnKFObserver.csh
'''+observertask.job()+observertask.directives()+'''

  [[EnKF]]
    inherit = '''+self.tf.execute+''', BATCH
    script = $origin/bin/EnKF.csh
'''+solvertask.job()+solvertask.directives()]

      self._dependencies += ['''

        # EnKF
        EnKFObserver => EnKF''']
