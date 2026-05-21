import re;

# NOTE: AI-generated code
def extract_classes(file_path) -> list[tuple[str, str]]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return []
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

    class_decl_regex = re.compile(
        r'(?:(?:public|protected|private|static|abstract|final)\s+)*class\s+(\w+)(?:\s+extends\s+\w+)?(?:\s+implements\s+\w+(?:\s*,\s*\w+)*)?\s*\{'
    )

    classes_found = []

    for match in class_decl_regex.finditer(content):
        class_name = match.group(1)

        start_idx = match.start()
        brace_start_idx = match.end() - 1  # Position of the opening '{'

        brace_count = 1
        current_idx = brace_start_idx + 1

        # Track curly braces to find the correct matching closing brace
        while brace_count > 0 and current_idx < len(content):
            char = content[current_idx]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
            current_idx += 1

        if brace_count == 0:
            end_idx = current_idx
            class_code = content[start_idx:end_idx]
            # Append as a tuple: (name, code)
            classes_found.append((class_name, class_code))

    return classes_found

