#!/bin/csh -f

# (C) Copyright 2023 UCAR
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

# Get ERA5 analysis (0-h forecast) for cold start initial conditions

# Process arguments
# =================
## args
# ArgDT: int, valid time offset beyond CYLC_TASK_CYCLE_POINT in hours
set ArgDT = "$1"

# ArgWorkDir: my location
set ArgWorkDir = "$2"

set test = `echo $ArgDT | grep '^[0-9]*$'`
set isNotInt = ($status)
if ( $isNotInt ) then
  echo "ERROR in $0 : ArgDT must be an integer, not $ArgDT"
  exit 1
endif

date

# Setup environment
# =================
source config/auto/build.csh
source config/auto/experiment.csh
source config/tools.csh
set ccyymmdd = `echo ${CYLC_TASK_CYCLE_POINT} | cut -c 1-8`
set hh = `echo ${CYLC_TASK_CYCLE_POINT} | cut -c 10-11`
set thisCycleDate = ${ccyymmdd}${hh}
set thisValidDate = `$advanceCYMDH ${thisCycleDate} ${ArgDT}`

source ./bin/getCycleVars.csh
set ccyymmdd = `echo ${thisValidDate} | cut -c 1-8`
set ccyymm = `echo ${thisValidDate} | cut -c 1-6`
set ccyy = `echo ${thisValidDate} | cut -c 1-4`
set gribFile_pl = e5.oper.an.pl/${ccyymm}  
set gribFile_sfc = e5.oper.an.sfc/${ccyymm}  

set WorkDir = ${ExperimentDirectory}/`echo "$ArgWorkDir" \
  | sed 's@{{thisValidDate}}@'${thisValidDate}'@' \
  `
echo "WorkDir = ${WorkDir}"
mkdir -p ${WorkDir}
cd ${WorkDir}

# ================================================================================================

if ( -e GETSUCCESS ) then
  echo "$0 (INFO): GETSUCCESS file already exists, exiting with success"
  echo "$0 (INFO): if regenerating the output files is desired, delete GETSUCCESS"

  date

  exit 0
endif

# ================================================================================================

set linkWPS = link_grib.csh
ln -sfv ${WPSBuildDir}/${linkWPS} .
rm -rf GRIBFILE.*

echo "Getting ERA5 analysis from RDA"
# RDA ERA5 forecasts directory
set ERA5gribdirRDA = /glade/campaign/collections/rda/data/ds633.0

# link ungribbed ERA5
#ln -sfv ${ERA5gribdirRDA}/${gribFile_pl}/e5.oper.an.pl*${ccyymmdd}*_${ccyymmdd}*.grb ./
#ln -sfv ${ERA5gribdirRDA}/${gribFile_sfc}/*grb ./
#ln -sfv ${ERA5gribdirRDA}/e5.oper.invariant/197901/*grb ./e5.oper.invariant.*${ccyymmdd}00_${ccyymmdd}23.grb
ln -sfv ${ERA5gribdirRDA}/e5.oper.invariant/197901/e5.oper.invariant.128_172_lsm.ll025sc.1979010100_1979010100.grb ./e5.oper.invariant.128_172_lsm.ll025sc.${ccyymmdd}00_${ccyymmdd}23.grb
./${linkWPS} e5*grb
#mv "PFILE:1979-01-01_00" "PFILE:2023-02-18_18"
#cp /glade/work/nghido/mpas_static_60kmduda-30kmjake/PFILE:1979-01-01_00 ./PFILE:2023-02-18_18_landsea
#cat PFILE:2023-02-18_18 PFILE:2023-02-18_18_landsea >> PFILE:2023-02-18_18
# check if the gribFile was linked
if ( ! -e "GRIBFILE.AAA") then
   echo "GRIBFILE.AAA is not in folder -- exiting"
   exit 1
endif

date

touch GETSUCCESS

exit 0
