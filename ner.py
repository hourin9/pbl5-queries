import os;
import sys
from typing import Any;
from cpgqls_client import CPGQLSClient, import_code_query;
import argparse;
from string import Template;
from pathlib import Path;
import tempfile;
import re;
import glob;
from pydriller import Repository;

from utils import bihyung, coraline;

def guess_project_name(path):
    return Path(path).name;

# Run Joern query with source path.
# NOTE: unused after changing to Lexer analysis.
def run_query(query, source):
    result = client.execute(import_code_query(source));
    print(result['success']);

    # Leave this here until I find a way to properly import
    # a Scala file in the client Joern
    with open("metrics.sc", "r") as f:
        metrics = f.read();

    query = f"""
        {metrics}
        {query}
    """

    result = client.execute(query);
    output = result['stdout'];
    print(output);

def sanitize_source(source):
    # NOTE: AI generated regex
    # This regex matches:
    # 1. Double-quoted strings: ".*?"
    # 2. Single-quoted strings: '.*?'
    # 3. Multi-line comments: /\*.*?\*/
    # 4. Single-line comments: //.*? followed by \r or \n
    pattern = r'("(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')|(/\*.*?\*/)|(//.*?(?:\r|\n|$))';

    def chomp(match):
        if match.group(1):
            return match.group(1);
        return "";

    # Step 1 & 2: Remove comments while protecting strings
    source = re.sub(pattern, chomp, source, flags=re.DOTALL);

    # Step 3: Remove remaining newlines
    source = source.replace('\n', '').replace('\r', '');
    return source;

# Not sanitizing code, but rather forcing it to fit the dataset's code
def please_fucking_run(source):
    source = re.sub(r'import .*;', '', source);

    # NOTE: AI generated function
    def replace_outside_strings(target, replacement, text):
        pattern = r'("(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')|' + re.escape(target);
        def handler(match):
            if match.group(1):
                return match.group(1);
            return replacement;
        return re.sub(pattern, handler, text);

    # Bullshit lexer can't properly separate the dot for classes.
    source = replace_outside_strings('.', ' . ', source);

    # Same with this.
    source = replace_outside_strings('@', ' @ ', source);

    return source;

def run_text(source):
    source = please_fucking_run(source);
    source = sanitize_source(source);
    # print(source);

    # Returns dict[str, Number]
    코럴라인 = coraline.analyze_code_sample(source);
    # print(코럴라인);
    return 코럴라인;

# Run Coraline analysis with path to source code file.
def run_once(path):
    with open(path) as file:
        source = file.read();
        비형 = bihyung.extract_classes(source);
        result_list = [];
        for classname, source in 비형:
            result = run_text(source);
            result["Code"] = sanitize_source(source);
            result["Class"] = classname;
            result_list.append(result);
        return result_list;

def run_dir(path) -> list[tuple[str, Any]]:
    result_list = [];
    orig_dir = os.getcwd();

    try:
        os.chdir(path);
        source_list = glob.glob("./**/*.java", recursive=True);
        for source in source_list:
            clean_source = os.path.normpath(source);
            for result in run_once(clean_source):
                result_list.append((clean_source, result));
    finally:
        os.chdir(orig_dir);

    return result_list;

def run_git(repo) -> tuple[str, list[tuple[str, Any]]]:
    for commit in Repository(repo, order="reverse").traverse_commits():
        path = commit.project_path;
        return (guess_project_name(path), run_dir(path));
    return ("",[]);

# Run Joern query with source path.
# NOTE: unused after changing to Lexer analysis.
def run_many(query):
    for line in sys.stdin:
        line = line.strip();
        output = guess_project_name(line);
        query = template.substitute(output=output);
        run_query(query, line);

import csv;
def export_csv(entries: list[tuple[str, Any]], project="unknown"):
    if not entries:
        print("empty metrics list");
        return;

    with open("csv.csv", mode="w") as f:
        first = entries[0][1];
        fields = ["File", "Project"] + list(first.keys());
        writer = csv.DictWriter(f, fieldnames=fields);
        writer.writeheader();

        for path, entry in entries:
            row = entry.copy();
            row["File"] = f"\"{path}\"";
            row["Project"] = project;
            writer.writerow(row);

if __name__ == "__main__":
    parser = argparse.ArgumentParser();
    parser.add_argument("-s", help="source code path");
    parser.add_argument("-d", help="find and parse entire directory");
    parser.add_argument("-r", help="git repository");
    parser.add_argument(
        "-t",
        help="parse code snippet",
        action="store_true"
    );
    args = parser.parse_args();

    server = "localhost:8000";
    client = CPGQLSClient(server);

    with open("ner.sc", "r") as file:
        template = Template(file.read());

        if args.t:
            source = sys.stdin.read();
            run_text(source);
        elif args.d:
            run_dir(args.d);
        elif args.s != None:
            run_once(args.s);
        elif args.r != None:
            project, result = run_git(args.r);
            export_csv(result, project);
        else:
            print("nothing to do. use -h for help.");

