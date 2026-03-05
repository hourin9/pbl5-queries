#!/bin/bash

build-one-dataset() {
    local name=$(basename "$1")
    if [ ! -f $name ]; then
        parse $1
    fi

    joern --batch --nocolors \
        --script joern_label.sc \
        --param cpgFile=.speaki/"$name".cpg.bin \
        --param project="$name" \
        > .speaki/thing.csv 2> /dev/null
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
            -o ".speaki/$(basename "$i").cpg.bin" \
            2> /dev/null 1>/dev/null
    done
}

mkdir -p .speaki
func=$1; shift; $func "$@"

