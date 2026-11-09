# 2024 historical station review: priority batch

Source: Ministry of Environment, 113-year (2024) Air Quality Annual Report.

Official PDF: https://service.moenv.gov.tw/File/Get/moenv/zh-tw/C6rMtsEWR5iKiVM

PDF SHA-256: 36311d057c007d5d2d7e80682206f521e9cf5ab1d7556499adde40339f01f84b

Evidence already archived in historical-source-pages.json by Actions run 42615797865. The companion CSV records 11 reviewed station-to-township identities: nine correction decisions and two retained identities (Wanli and Fuguei Cape). It is an evidence/decision table, not an updated pollution-income dataset.

## Interpretation

- PDF page numbers are 1-based file pages, not printed appendix page numbers.
- siteid is the project's monitoring station ID, NOT the annual report table's serial number. Names were used to cross-check identities.
- report_address transcribes the report with whitespace removed; relocation_date converts the report's ROC calendar date to Gregorian format. Blank relocation fields mean no relocation date is asserted here.
- county_2024 and township_2024 are supported by the 2024 report's station addresses, cross-checked with the relocation table where listed. This does not independently certify continuous operation, coordinates, measurement validity, or absence of all within-year changes.
- Qianjin moved to Sanmin District on 2022-03-08 according to PDF page 84; the current metadata township field must not override this historical evidence.
- Wanli appears in the 2024 report and must not be excluded merely because it is absent from the current station snapshot. Fuguei Cape has a descriptive location rather than a street number.
- These 11 decisions do not mark the remaining 67 project stations as historically reviewed. The previous historical-review.csv and summary.json remain unchanged records of the earlier automated run.

## Analysis safeguards and remaining work

Original station-township mappings, income/population-density joins, annual means, statistical summaries and published pages are not changed by this commit. Before producing revised associations, finish historical review, rejoin the actual 2024 income/density source tables by corrected administrative identity, report missing joins explicitly, and audit hourly validity and daily/quarterly annual-mean eligibility. Do not only replace township labels while retaining the old area's socioeconomic values.

The automated address warnings for Pingzhen, Qianzhen and Fuxing are parser false positives on the supplied addresses; the regex can stop at the embedded character 鎮 or consume 區 as part of a following token. They are not independent evidence of an address mismatch. The parser itself is not changed by this commit.
