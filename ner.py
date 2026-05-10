from cpgqls_client import CPGQLSClient, import_code_query, workspace_query;
import argparse;

def clean_joern_output(raw_str):
    import re;
    cleaned = re.sub(r'val res\d+:.*', '', raw_str).strip();
    return cleaned;

def main(query, args):
    result = client.execute(import_code_query(args.s));
    print(result['success']);

    result = client.execute(query);
    with open("joern.json", "w") as file:
        output = clean_joern_output(result['stdout']);
        file.write(output);

if __name__ == "__main__":
    parser = argparse.ArgumentParser();
    parser.add_argument("-s", help="source code path", required=True);
    args = parser.parse_args();

    server = "localhost:8000";
    client = CPGQLSClient(server);

    with open("ner.sc", "r") as file:
        query = file.read();
        main(query, args);

