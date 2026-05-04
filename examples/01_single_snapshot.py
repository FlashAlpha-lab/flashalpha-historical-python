"""Example 1 — pull a single point-in-time snapshot.

What did SPY dealer positioning look like at the COVID-crash close on
March 16, 2020? Run me with FLASHALPHA_API_KEY set in your environment.
"""

import os

from flashalpha_historical import FlashAlphaHistorical

hx = FlashAlphaHistorical(os.environ["FLASHALPHA_API_KEY"])

snap = hx.exposure_summary("SPY", at="2020-03-16T15:30:00")

print(f"SPY @ {snap['as_of']}")
print(f"  spot:        {snap['underlying_price']}")
print(f"  regime:      {snap['regime']}")
print(f"  net GEX:     ${snap['exposures']['net_gex']:,}")
print(f"  net DEX:     ${snap['exposures']['net_dex']:,}")
print(f"  net VEX:     ${snap['exposures']['net_vex']:,}")
print(f"  gamma flip:  {snap['gamma_flip']}")
print()
print("interpretation:")
for k, v in snap["interpretation"].items():
    print(f"  {k}: {v}")
