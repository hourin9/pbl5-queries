"Name,Project,Logical Lines,Distinct Operators,Distinct Operands,Total Operators,Total Operands,Vocabulary,Length,Calculated Length,Volume,Difficulty,Effort,Time Required,Bugs,Cyclomatic Complexity,Code" #> "$output.csv"

cpg.method
    .filterNot(m => m.isExternal || m.name.startsWith("<"))
    .foreach { m =>
        // Needs fixed. Currently Physical lines
        val lloc = m.numberOfLines

        // Verify correctness
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

        val cyccomp = Metrics.CyclomaticComp(m)

        s"$${m.name},$output,$$lloc,$$n1,$$n2,$$N1,$$N2,$$vocab,$$length,$$clength,$$volume,$$difficulty,$$effort,$$time,$$bug,$$cyccomp,\"$${m.code}\"" #>> "$output.csv"
    }

