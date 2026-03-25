#!/bin/bash

build-one-dataset() {
    local name=$(basename "$1")
    local cpg_path=".speaki/$name.cpg.bin"
    if [ ! -f "$cpg_path" ]; then
        parse $1
    fi
    echo Parsed $name

    # joern --batch --nocolors \
    #     --script joern_label.sc \
    #     --param cpgFile=.speaki/"$name".cpg.bin \
    #     --param project="$name" \
    #     2> /dev/null | grep -v "^\[" >> .speaki/thing.csv

    temp=$(mktemp)

    joern --batch --nocolors \
        --script joern_json.sc \
        --param cpgFile=.speaki/"$name.cpg.bin" \
        2> /dev/null > "$temp"

    tail -n +2 "$temp" > ".speaki/$name.json"

    rm "$temp"
    echo Processed $name
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

distribute() {
    local cur=$(pwd)
    pushd .speaki > /dev/null
    tar cvf - * | gzip -9 - > "$cur/dataset.tar.gz"
    popd > /dev/null
}

init() {
    mkdir -p .speaki/

    # dm bash
    echo project,cpg_id,method_name,\
long_name,\
long_method,\
long_param_lists\
        > .speaki/thing.csv
}

mkdir -p .speaki
func=$1; shift; $func "$@"

