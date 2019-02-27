#!/bin/bash

# Script that creates the conda/python environment for the web validation service and
# installs the service.
#
# Before running it you need to copy a private ssh key next to into the same folder 
# which can be used to clone the necessary repositories.
#
#Celery requires RabbitMQ and Redis installed locally. Since the Reddis package in the 
# debain repository seems to be broken, Redis and RabitMQ has to be installed manually.

# install paths for miniconda and the app itself:
if [ "x$INSTALL_DIR" == "x" ]; then
    INSTALL_DIR="/var/lib/qa4sm-web-val"
fi 
if [ "x$MINICONDA_PATH" == "x" ]; then
    MINICONDA_PATH="/opt/miniconda"
fi
if [ "x$TOOL_DIR" == "x" ]; then
    TOOL_DIR="/opt/tools"
fi
if [ "x$PYTHON_ENV_DIR" == "x" ]; then
    PYTHON_ENV_DIR="/var/lib/qa4sm-conda"
fi 

# dir this script is in
THIS_SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

echo "$INSTALL_DIR, $MINICONDA_PATH, $TOOL_DIR, $PYTHON_ENV_DIR, $THIS_SCRIPT_DIR"

# external software
MINICONDA_URL="https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh"
MATPLOTLIB_BASEMAP_URL="https://github.com/matplotlib/basemap/archive/v1.1.0.tar.gz"

MINICONDA_PKG="$TOOL_DIR/miniconda.sh"
MATPLOTLIB_BASEMAP_PKG="$TOOL_DIR/mpl_basemap.tar.gz"

# tmp dir structure
TMP_BASE_DIR="/tmp/"
TEMP_DIR=$(mktemp -d -p $TMP_BASE_DIR -t "web-val.XXXXXXXX")
chmod 700 $TEMP_DIR
echo "Tmp dir: $TEMP_DIR"
SSH_CONFIG="$TEMP_DIR/ssh_config"

# clean up
if [[ -e "$INSTALL_DIR" ]]; then
    rm -Rf "$INSTALL_DIR"
fi
if [[ -e "$PYTHON_ENV_DIR" ]]; then
    rm -Rf "$PYTHON_ENV_DIR"
fi

mkdir "$INSTALL_DIR"

# prepare ssh config file for git
echo -e "Host github.com\n\tStrictHostKeyChecking no\n\tIdentityFile $TEMP_DIR/id_rsa\n" > $SSH_CONFIG
echo -e "Host git.eodc.eu\n\tStrictHostKeyChecking no\n\tIdentityFile $TEMP_DIR/id_rsa\n" >> $SSH_CONFIG

# copy ssh key
touch $TEMP_DIR/id_rsa
chmod 600 $TEMP_DIR/id_rsa
cp "$THIS_SCRIPT_DIR/id_rsa" "$TEMP_DIR/id_rsa"

# download basemap only if not present
if [ ! -e "$MATPLOTLIB_BASEMAP_PKG" ]; then
    echo "Downloading matplotlib basemap"
    curl -L -s -o $MATPLOTLIB_BASEMAP_PKG $MATPLOTLIB_BASEMAP_URL
fi

#Install conda and create virtual env.
echo "Downloading miniconda installer"
# download only if newer than existing
if [ -e "$MINICONDA_PKG" ]; then
    ZFLAG="-z $MINICONDA_PKG"
else
    ZFLAG=""
fi
CONDA_HTTP_CODE=$(curl -L -s -w "%{http_code}" -o $MINICONDA_PKG $ZFLAG $MINICONDA_URL)
echo "$CONDA_HTTP_CODE"

# only install if new conda version
if [ "$CONDA_HTTP_CODE" != "304" ]; then
    echo "Installing miniconda"
    if [[ -e $MINICONDA_PATH ]]; then
        rm -Rf $MINICONDA_PATH
    fi
    bash $MINICONDA_PKG -b -p $MINICONDA_PATH
fi    
export PATH="$MINICONDA_PATH/bin:$PATH"
    
# echo "Creating python virtual environment in $PYTHON_ENV_DIR"
conda create --yes --prefix $PYTHON_ENV_DIR -c conda-forge python=3.6 numpy scipy pandas cython pytest pip matplotlib pyproj django pyresample pygrib
source activate $PYTHON_ENV_DIR

pip install $MATPLOTLIB_BASEMAP_PKG
pip install pynetcf
pip install ascat
pip install pybufr-ecmwf
pip install c3s_sm
pip install coverage
pip install pygeogrids
pip install pytest-django
pip install django-widget-tweaks
pip install psycopg2-binary
pip install pytest-cov
pip install pytest-mpl
pip install celery==4.1.1
pip install celery[redis]
pip install gldas
pip install smap-io
pip install django-countries
pip install cartopy
pip install --upgrade --force-reinstall netcdf4

cd $TEMP_DIR


sh -c "GIT_SSH_COMMAND='ssh -F $SSH_CONFIG' git clone -b master --single-branch git@git.eodc.eu:pbuttinger/ismn.git"
cd ismn
git checkout 40ee729f29cfd7e6a909d7ae9262f2ea1a410715
rm requirements.txt
touch requirements.txt
python setup.py install
cd $TEMP_DIR
rm -rf ismn

git clone -b master --single-branch https://github.com/TUW-GEO/pytesmo.git
cd pytesmo
rm requirements.txt
touch requirements.txt
python setup.py install
cd $TEMP_DIR
rm -rf pytesmo

#Clone the  web validation service repo
sh -c "GIT_SSH_COMMAND='ssh -F $SSH_CONFIG' git clone -b master --single-branch git@git.eodc.eu:QA4SM/web-validation-service.git \"$INSTALL_DIR\""

# clean up
rm -Rf $TEMP_DIR

echo "Installation ready in $INSTALL_DIR"