# Integrated 2024 reanalysis

Status: completed_with_explicit_exclusions

## Stage status
- history: {'status': 'completed'}
- income: {'status': 'completed'}
- annual_quality: {'status': 'completed'}

## Statistics

| Scenario | Item | n | Pearson | Spearman | Partial raw density |
|---|---|---:|---:|---:|---:|
| A_old_same_sample | NO2 | 77 | 0.33503367187398597 | 0.41878533060463685 | 0.05230858870056036 |
| A_old_same_sample | PM2.5 | 77 | -0.07146224115075059 | -0.09416327096465499 | -0.0439774832470719 |
| A_old_same_sample | SO2 | 77 | -0.08976735981276932 | -0.029854081859658172 | -0.05633662111449539 |
| B_mapping_only | NO2 | 77 | 0.3160114675369661 | 0.4527719016270819 | 0.07247536656689893 |
| B_mapping_only | PM2.5 | 77 | -0.073864520419688 | -0.07603822998783548 | -0.06883133971872746 |
| B_mapping_only | SO2 | 77 | -0.0739355223054175 | -0.0167221003707688 | -0.0439226477918183 |
| C_mean_only | NO2 | 77 | 0.3351311785547439 | 0.4192454331432049 | 0.051895765756694766 |
| C_mean_only | PM2.5 | 77 | -0.06929658163601794 | -0.09630603421570047 | -0.04251359276884135 |
| C_mean_only | SO2 | 77 | -0.08767896203268832 | -0.02972262399149587 | -0.055035575841466955 |
| D_mapping_and_mean | NO2 | 77 | 0.3160912994425608 | 0.4531925833974158 | 0.07227687886049536 |
| D_mapping_and_mean | PM2.5 | 77 | -0.07186784326737027 | -0.07816793145015037 | -0.06745228233625072 |
| D_mapping_and_mean | SO2 | 77 | -0.07223294272520911 | -0.016459174264310174 | -0.04291836409563201 |
| A_old_all_stations | NO2 | 78 | 0.31711597074260217 | 0.4026153060039514 | 0.049618934125423425 |
| A_old_all_stations | PM2.5 | 78 | -0.041823950370614385 | -0.07169324568841563 | -0.007538471072921122 |
| A_old_all_stations | SO2 | 78 | -0.07833270559884686 | -0.019564200225785675 | -0.04364978680329793 |

## Interpretation
Compare A_old_all_stations with A_old_same_sample for sample-selection effects; A vs B for mapping; A vs C for daily-mean/duplicate handling; A vs D for joint changes. These are descriptive changes, not causal effects.

## Limitations
- 2024 report supports administrative assignment, not continuous station operation or historical coordinates.
- Unresolved historical addresses and unmatched socioeconomic keys excluded explicitly.
- Conservative unflagged finite nonnegative values used; unknown tokens rejected, never stripped or imputed.
- Official 45-minute hourly sampling validity cannot be certified from these exported values.
- Year means are equal-weight means of days with at least 16 accepted hours; each quarter must reach 75% of calendar days.
- Correlations use stations, not independent townships or personal exposures; no causal conclusion.
- A/B/C/D on the same final sample separates mapping changes, mean changes and joint effects.
- Raw density reproduces original control specification; log1p density is a sensitivity model.
