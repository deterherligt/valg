# Disclaimer

## Not official results

This tool is an unofficial viewer of Danish election data and is not affiliated with or
endorsed by Indenrigsministeriet, the Danish election authority, or Netcompany.

**Official results are published at [valg.dk](https://valg.dk).** During the foreløbig
optælling (preliminary count on election night), results are preliminary and subject to
correction. Always consult the official source for authoritative figures. Do not cite
output from this tool as an official source.

## Seat projections are approximate

Projected seat totals are calculated using a simplified model:

- Kredsmandater are allocated using D'Hondt per storkreds based on available party votes.
- Tillægsmandater are approximated via national Saint-Laguë and **will differ from the
  official final allocation**, which requires a full multi-pass calculation across all
  storkredse that is only possible once all results are final.

Projections are intended to give a directional signal during the count. They are not
a substitute for the official seat allocation published by Indenrigsministeriet.

## Data source

Election data is fetched from the Danish election authority's public SFTP server
(`data.valg.dk`), operated by Netcompany on behalf of Indenrigsministeriet, using
publicly documented access credentials. This data is made available for public use
under the Danish Open Government License (DOGL).

The raw data archive (`valg-data/`) is an unofficial snapshot of this public data.
It is not the authoritative record. For the authoritative record, refer to valg.dk.

## No warranty

This software is provided as-is with no warranty of any kind. See LICENSE for details.
