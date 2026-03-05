#!/bin/bash

build-one-dataset() {
    local name=$(basename "$1")
    if [ ! -f $name ]; then
        parse $1
    fi

    joern --batch --nocolors \
        --script joern_label.sc \
        --param cpgFile="$name".cpg.bin \
        --param project="$name" \
        > thing.csv 2> /dev/null
}

build-dataset() {
    set -e

    for i in $@; do
        build-one-dataset "$i"
    done
}

parse() {
    set -e

    for i in $@; do
        joern-parse $i --language c \
            -o "$(basename "$i").cpg.bin"
    done
}

func=$1; shift; $func "$@"

