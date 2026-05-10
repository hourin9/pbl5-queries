"method_name,project,length,clength,vocab,volume,difficulty,effort,time,bugs,code" #> "$output.csv"

cpg.method
    .filterNot(m => m.isExternal || m.name.startsWith("<"))
    .foreach { m =>
        val operators = Metrics.CalcOperators(m)
        val n1 = operators.distinct.size
        val N1 = operators.size

        val operands = Metrics.CalcOperands(m)
        val n2 = operands.distinct.size
        val N2 = operands.size

        val length = N1 + N2
        val clength = Metrics.CalculatedLength(n1, n2)
        val vocab = n1 + n2

        val volume = Metrics.Volume(vocab, length)
        val difficulty = Metrics.Difficulty(n1, n2, N2)
        val effort = volume * difficulty

        val time = Metrics.RequiredTime(effort)

        val bug = Metrics.EstimatedBugs(effort)

        s"$${m.name},$output,$$length,$$clength,$$vocab,$$volume,$$difficulty,$$effort,$$time,$$bug,\"$${m.code}\"" #>> "$output.csv"
    }

