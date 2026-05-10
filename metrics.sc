object Metrics {
    private def _Log2(n: Double) = Math.log(n) / Math.log(2)

    def CalcOperators(m: Method) =
        m.ast.isCall.name.l

    def CalcOperands(m: Method) =
        m.ast.isIdentifier.name.l ++ m.ast.isLiteral.code.l

    def CalculatedLength(n1: Int, n2: Int) =
        n1 * _Log2(n1) + n2 * _Log2(n2)

    def Volume(vocab: Double,  length: Int) =
        if (vocab > 0)
            length * (Math.log(vocab) / Math.log(2))
        else
            0.0

    def Difficulty(n1: Int, n2: Int, N2: Int) =
        if (n2 > 0)
            (n1.toDouble / 2.0) * (N2.toDouble / n2.toDouble)
        else
            0.0

    def RequiredTime(e: Double) =
        e / 18.0

    def EstimatedBugs(e: Double) =
        Math.pow(e, 2.0/3.0) / 3000.0
}

