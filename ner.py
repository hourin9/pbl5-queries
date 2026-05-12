import os;
import sys;
from cpgqls_client import CPGQLSClient, import_code_query;
import argparse;
from string import Template;
from pathlib import Path;
import tempfile;
import re;

from utils import coraline;

def guess_project_name(path):
    return Path(path).name;

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

def run_once(query, args):
    output = guess_project_name(args.s);
    query = query.substitute(output=output);

    run_query(query, args.s);

def sanitize_source(source):
    # Note: AI generated regex
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

    # Note: AI generated function
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

def run_text(query):
    source = sys.stdin.read();
    source = please_fucking_run(source);
    source = sanitize_source(source);
    # print(source);

    코럴라인 = coraline.analyze_code_sample(source);
    print(코럴라인);

def run_many(query):
    for line in sys.stdin:
        line = line.strip();
        output = guess_project_name(line);
        query = template.substitute(output=output);
        run_query(query, line);

if __name__ == "__main__":
    parser = argparse.ArgumentParser();
    parser.add_argument("-s", help="source code path");
    parser.add_argument(
        "-c",
        help="enable continous mode",
        action="store_true"
    );
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
            run_text(template);
        elif args.c:
            run_many(template);
        elif args.s != None:
            run_once(template, args);
        else:
            print("nothing to do. use -h for help.");

