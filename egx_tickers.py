# Full EGX ticker list scraped from https://stockanalysis.com/list/egyptian-stock-exchange/
# (224 stocks, per site header, as of 2026-08-22)

TICKERS = [
    "COMI", "SWDY", "TMGH", "ETEL", "EGAL", "QNBE", "MFPC", "EAST", "HDBK", "ABUK",
    "ALCN", "EFIH", "ORAS", "ADIB", "FWRY", "EMFD", "SCTS", "ORHD", "EFID", "PHDC",
    "OCDI", "VLMR", "VLMRA", "CANA", "GPPL", "JUFO", "HRHO", "BIOC", "BTFH", "GBCO",
    "IRON", "HELI", "FERC", "CIEB", "FAIT", "FAITA", "RAYA", "EXPA", "EGCH", "ARCC",
    "SCEM", "CLHO", "VALU", "CCAP", "PHAR", "CIRA", "EFIC", "MCQE", "SKPC", "TAQA",
    "MBSC", "MTIE", "AMES", "POUL", "SAUD", "EGTS", "ORWE", "NIPH", "EGSA", "MASR",
    "UBEE", "MOIL", "AMOC", "EGBE", "MHOT", "TALM", "ATQA", "ISPH", "RMDA", "CSAG",
    "CICH", "BINV", "IFAP", "OIH", "MPRC", "OLFI", "PRDC", "MIPH", "MOIN", "ISMQ",
    "PHTV", "BONY", "MPCI", "EGAS", "SPHT", "AMIA", "DOMT", "CPCI", "ZMID", "KORA",
    "AFMC", "SUGR", "AXPH", "ELEC", "SPIN", "ACAP", "ENGC", "NINH", "NAPR", "GOUR",
    "OCPH", "CNFN", "ARAB", "MICH", "AMER", "DSCW", "KABO", "SVCE", "GSSC", "WCDF",
    "MFSC", "UNIT", "KZPC", "GDWA", "OFH", "ACGC", "AJWA", "UEFM", "CRST", "SDTI",
    "SAIB", "ADCI", "ISMA", "INFI", "ELKA", "ASCM", "ACTF", "ELSH", "NAHO", "ZEOT",
    "LCSW", "GTWL", "CFGH", "ALRA", "DAPH", "ACAMD", "SMFR", "ETRS", "EDFM", "MILS",
    "LUTS", "MPCO", "CEFM", "NARE", "PHGC", "ATLC", "GPIM", "AALR", "EALR", "GGCC",
    "RACC", "EHDR", "GGRN", "MOSC", "CAED", "ADPC", "IDRE", "ECAP", "ODIN", "WKOL",
    "MAAL", "SNFC", "SCFM", "MENA", "ICID", "DTPP", "PRCL", "UEGC", "NCCW", "DEIN",
    "NHPS", "CERA", "SEIG", "SEIGA", "OBRI", "NDRL", "MEPA", "SIPC", "COSG", "AMII",
    "ALUM", "AFDI", "RREI", "AIDC", "RTVC", "GTEX", "ASPI", "POCO", "EBSC", "KRDI",
    "TANM", "MCRO", "MOED", "PRMH", "UNIP", "APSW", "KWIN", "ROTO", "MEGM", "TYCN",
    "ICLE", "RUBX", "SPMD", "AIHC", "EASB", "EEII", "RAKT", "AREH", "CCRS", "GRCA",
    "EPCO", "GIHD", "ELWA", "ELNA", "DGTZ", "TRTO", "DCCC", "MMAT", "NEDA", "EPPK",
    "GMCI", "EOSB", "CPME", "COPR",
]

ZERO_DATA_TICKERS = {
    "QNBE", "VLMR", "VLMRA", "VALU", "TAQA", "UBEE", "BONY", "KORA",
    "ACAP", "NAPR", "GOUR", "CRST", "ACTF", "GTWL", "ALRA", "NARE",
    "PHGC", "GPIM", "GGRN", "AMII", "AIDC", "GTEX", "POCO", "KRDI",
    "TANM", "TYCN", "AIHC", "DGTZ", "CPME",
}

# JOB 1: excluded for unexplained bad data, NOT for missing data. Kept in a
# separate set from ZERO_DATA_TICKERS so the reason for each exclusion stays
# auditable; VALID_TICKERS filters on the union of the two.
#
# COPR — 2023-07-05 close prints 40.93 -> 0.61, a 67:1 ratio. No plausible
# corporate action produces that; it is off the split ladder in
# split_corrections.py entirely and cannot be corrected, only dropped.
BAD_DATA_TICKERS = {
    "COPR",
}

EXCLUDED_TICKERS = ZERO_DATA_TICKERS | BAD_DATA_TICKERS

VALID_TICKERS = [t for t in TICKERS if t not in EXCLUDED_TICKERS]

if __name__ == "__main__":
    print(f"Total: {len(TICKERS)}")
    print(f"Unique: {len(set(TICKERS))}")
    print(f"Zero-data: {len(ZERO_DATA_TICKERS)}")
    print(f"Bad-data:  {len(BAD_DATA_TICKERS)} ({', '.join(sorted(BAD_DATA_TICKERS))})")
    print(f"Excluded:  {len(EXCLUDED_TICKERS)}")
    print(f"Valid: {len(VALID_TICKERS)}")
