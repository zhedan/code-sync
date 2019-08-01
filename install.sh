#!/bin/bash

CUR_DIR=$(cd $(dirname $0) && pwd)
INSTALL_DIR=/home/code-sync

function main() {
  mkdir -p $INSTALL_DIR 

  if [ ! $CUR_DIR -ef $INSTALL_DIR ]; then
    cp -r $CUR_DIR/* $INSTALL_DIR/
  fi

  for i in $CUR_DIR/bin/*; do
    chmod +x $i
    cp $i /bin/
  done

  pip install -r $CUR_DIR/requirements.txt
  mkdir -p $CUR_DIR/venv

  if [ ! -f $CUR_DIR/venv/bin/activate ]; then
    virtualenv $CUR_DIR/venv
  fi

  source $CUR_DIR/venv/bin/activate

  pip install -r $CUR_DIR/test_requirements.txt

  if ! type socat &>/dev/null; then
    echo 1>&2 "socat must be installed" 
    exit 1
  fi

  echo "installed successfully"
}

main $@
