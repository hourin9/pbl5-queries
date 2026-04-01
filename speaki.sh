#!/bin/bash

JOERN_SCRIPT="${JOERN_SCRIPT:-joern_json.sc}"

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
        --script "$JOERN_SCRIPT" \
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

batch() {
    local repo=$(realpath $1)
    local dir_list=()
    pushd .speaki > /dev/null
    while IFS= read -r repo_url || [ -n "$repo_url" ]; do
        [[ -z "$repo_url"  ]] && continue
        echo "$repo_url"
        dir_name=$(basename "$repo_url" .git)
        dir_list+=("$dir_name")
        git clone --depth 1 "$repo_url"
    done < "$repo"
    popd > /dev/null
    build-dataset "${dir_list[@]/#/.speaki/}"
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
echo "Script file is $JOERN_SCRIPT"
func=$1; shift; $func "$@"

