import sys;
from cpgqls_client import CPGQLSClient, import_code_query, workspace_query;
import argparse;
from string import Template;
from pathlib import Path;

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
    args = parser.parse_args();

    server = "localhost:8000";
    client = CPGQLSClient(server);

    with open("ner.sc", "r") as file:
        template = Template(file.read());

        if args.c:
            run_many(template);
        elif args.s != None:
            run_once(template, args);
        else:
            print("nothing to do. use -h for help.");
