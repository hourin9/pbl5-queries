"method_name,project,length,vocab,volume,difficulty,effort,time,bugs,code" #> "$output.csv"

cpg.method
    .filterNot(m => m.isExternal || m.name.startsWith("<"))
    .foreach { m =>
        val operators = m.ast.isCall.name.l
        val n1 = operators.distinct.size
        val N1 = operators.size

        val operands = m.ast.isIdentifier.name.l ++ m.ast.isLiteral.code.l
        val n2 = operands.distinct.size
        val N2 = operands.size

        val length = N1 + N2
        val vocab = n1 + n2

        val volume = if (vocab > 0) length * (Math.log(vocab) / Math.log(2)) else 0.0
        val difficulty = if (n2 > 0) (n1.toDouble / 2.0) * (N2.toDouble / n2.toDouble) else 0.0
        val effort = volume * difficulty

        val time = effort.toDouble / 18

        val bug = Math.pow(effort, 2.0/3.0) / 3000.0

        s"$${m.name},$output,$$length,$$vocab,$$volume,$$difficulty,$$effort,$$time,$$bug,\"$${m.code}\"" #>> "$output.csv"
    }

