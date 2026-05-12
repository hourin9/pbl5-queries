from pygments.lexers import JavaLexer;
from pygments.token import Token;
from math import log2;
import re;

def count_lines_of_code(code):
    lines = code.split(";")
    total_lines = len(lines)
    blank_lines = sum(1 for line in lines if line.strip() == '')
    comment_lines = sum(1 for line in lines if line.strip().startswith('//') or re.match(r'/\*.*\*/', line.strip()))

    # Multi-line comments
    in_multi_line_comment = False
    multi_line_comment_lines = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/*"):
            in_multi_line_comment = True
        if in_multi_line_comment:
            multi_line_comment_lines += 1
        if stripped.endswith("*/"):
            in_multi_line_comment = False

    logical_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith('//') and not in_multi_line_comment)

    return {
        'Logical Lines': logical_lines,
        'Multi-line Strings': multi_line_comment_lines
    }

def halstead_metrics(code):
    lexer = JavaLexer()
    tokens = lexer.get_tokens(code)

    operators = []
    operands = []

    for token_type, value in tokens:
        if token_type in Token.Operator:
            operators.append(value)
        elif token_type in (Token.Name, Token.Literal.Number, Token.Literal.String):
            operands.append(value)

    print("operands: ", operands);

    # Distinct operators and operands
    distinct_operators = len(set(operators))
    distinct_operands = len(set(operands))

    # Total operators and operands
    total_operators = len(operators)
    total_operands = len(operands)

    # Halstead calculations
    vocabulary = distinct_operators + distinct_operands
    length = total_operators + total_operands

    # Avoid log2(0) by checking if distinct_operators and distinct_operands are greater than 0
    calculated_length = (
        (distinct_operators * log2(distinct_operators) if distinct_operators > 0 else 0) +
        (distinct_operands * log2(distinct_operands) if distinct_operands > 0 else 0)
    )

    cc = calculate_cyclomatic_complexity(code)

    volume = length * log2(vocabulary) if vocabulary > 0 else 0
    difficulty = (distinct_operators / 2) * (total_operands / distinct_operands) if distinct_operands > 0 else 0
    effort = difficulty * volume
    time_required = effort / 18
    delivered_bugs = volume / 3000

    return {
        'Distinct Operators': distinct_operators,
        'Distinct Operands': distinct_operands,
        'Total Operators': total_operators,
        'Total Operands': total_operands,
        'Vocabulary': vocabulary,
        'Length': length,
        'Calculated Length': calculated_length,
        'Volume': volume,
        'Difficulty': difficulty,
        'Effort': effort,
        'Time Required': time_required,
        'Bugs': delivered_bugs,
        'Cyclomatic Complexity': cc,
    }


def calculate_cyclomatic_complexity(method):
    # Count number of conditional statements
    keywords = ['if', 'else if', 'for', 'while', 'case', 'catch']
    cc = 1  # Default complexity of 1
    for keyword in keywords:
        cc += method.count(keyword)
    return cc

# Main function to analyze the code
def analyze_code_sample(code):
    # Get line metrics
    line_metrics = count_lines_of_code(code)

    # Get Halstead metrics
    halstead = halstead_metrics(code)

    # Combine metrics
    return {**line_metrics, **halstead}

