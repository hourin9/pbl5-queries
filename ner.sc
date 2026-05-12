"Name,Project,Logical Lines,Distinct Operators,Distinct Operands,Total Operators,Total Operands,Vocabulary,Length,Calculated Length,Volume,Difficulty,Effort,Time Required,Bugs,Cyclomatic Complexity,Code" #> "$output.csv"

cpg.typeDecl
    .filterNot(t => t.isExternal)
    .foreach { t =>
        println(t.name)

        // Needs fixed. Currently Physical lines
        val startingLine = t.lineNumber.getOrElse(0);
        val endingLine = t.astMinusRoot.lineNumber.l.max
        val lloc = endingLine - startingLine

        // Verify correctness
        val allMethods = t.method.l
        val operators = allMethods.flatMap(Metrics.CalcOperators)
        val operands = allMethods.flatMap(Metrics.CalcOperands)

        val n1 = operators.distinct.size
        val N1 = operators.size

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

        val cyccomp = allMethods.map(Metrics.CyclomaticComp).sum

        s"$${t.name},$output,$$lloc,$$n1,$$n2,$$N1,$$N2,$$vocab,$$length,$$clength,$$volume,$$difficulty,$$effort,$$time,$$bug,$$cyccomp,\"$${t.code}\"" #>> "$output.csv"
    }

