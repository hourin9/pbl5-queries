import os;
import sys;
from cpgqls_client import CPGQLSClient, import_code_query;
import argparse;
from string import Template;
from pathlib import Path;
import tempfile;
import re;
import glob;

from utils import coraline;

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
    print(코럴라인);

# Run Coraline analysis with path to source code file.
def run_once(path):
    with open(path) as file:
        source = file.read();
        return run_text(source);

def run_dir(path):
    result_list = [str, any]
    source_list = glob.glob(f"{path}/**/*.java", recursive=True);
    for source in source_list:
        result = run_once(source);
        result_list += [source, result];
    return result_list;

# Run Joern query with source path.
# NOTE: unused after changing to Lexer analysis.
def run_many(query):
    for line in sys.stdin:
        line = line.strip();
        output = guess_project_name(line);
        query = template.substitute(output=output);
        run_query(query, line);

if __name__ == "__main__":
    parser = argparse.ArgumentParser();
    parser.add_argument("-s", help="source code path");
    parser.add_argument( "-d", help="find and parse entire directory");
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
        else:
            print("nothing to do. use -h for help.");

