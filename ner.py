from cpgqls_client import CPGQLSClient, import_code_query, workspace_query;
import argparse;
from string import Template;
from pathlib import Path;

def guess_project_name(path):
    return Path(path).name;

def main(query, args):
    result = client.execute(import_code_query(args.s));
    print(result['success']);

    result = client.execute(query);
    with open("joern.json", "w") as file:
        output = result['stdout'];
        file.write(output);

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

