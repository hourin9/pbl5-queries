from cpgqls_client import CPGQLSClient, import_code_query, workspace_query;
import argparse;
from string import Template;
from pathlib import Path;

def guess_project_name(path):
    return Path(path).name;

def main(query, args):
    result = client.execute(import_code_query(args.s));
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser();
    parser.add_argument("-s", help="source code path", required=True);
    args = parser.parse_args();

    server = "localhost:8000";
    client = CPGQLSClient(server);

    with open("ner.sc", "r") as file:
        output = guess_project_name(args.s);
        query = Template(file.read());
        query = query.substitute(output=output);
        main(query, args);

