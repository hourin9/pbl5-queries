"method_name,project,length,vocab,code" #> "$output.csv"

cpg.method
    .filterNot(m => m.isExternal || m.name.startsWith("<"))
    .foreach { m =>
        val operators = m.ast.isCall.name.l
        val n1 = operators.distinct.size
        val N1 = operators.size

        val operands = m.ast.isIdentifier.name.l ++ m.ast.isLiteral.code.l
        val n2 = operands.distinct.size
        val N2 = operands.size

        val length = N1 + N2;
        val vocab = n1 + n2;

        s"$${m.name},$output,$$length,$$vocab,\"$${m.code}\"" #>> "$output.csv"
    }

