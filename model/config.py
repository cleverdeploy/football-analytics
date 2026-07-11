"""All tunable model constants in one place."""

# --- Elo -> match outcome ---------------------------------------------------
HOME_ADV = 100.0          # Elo points for a true home side (knockout WC = neutral)
MAX_GOALS = 10            # Poisson grid upper bound per side
LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0
CALIB_MIN_DATE = "1970-01-01"   # matches used to fit the Elo-diff -> goals map
ET_RATE_FACTOR = 1 / 3    # extra time = 30min of a 90min match
PENS_SPLIT = 0.5          # penalty shootouts treated as a coin flip

# --- lineup -> Elo adjustment ------------------------------------------------
# Elo delta = LINEUP_ELO_SCALE * ln(Q_selected / Q_best). Calibrated so that
# benching a Haaland-class player (~30-40% of XI value) costs ~50-65 Elo,
# i.e. ~7-9 win-prob points against an even opponent.
LINEUP_ELO_SCALE = 150.0
MAX_LINEUP_PENALTY = -400.0

# Squad position bucket preferred for each pitch band
BAND_PREF = {"GK": "GK", "D": "DF", "DM": "MF", "M": "MF", "AM": "MF", "F": "FW"}

# Effective-value multiplier for a (squad bucket, pitch band) pairing.
# Missing pairs fall back to OOP_DEFAULT.
OOP_DISCOUNT = {
    ("GK", "GK"): 1.0,
    ("DF", "D"): 1.0, ("DF", "DM"): 0.85, ("DF", "M"): 0.7, ("DF", "AM"): 0.55, ("DF", "F"): 0.5,
    ("MF", "DM"): 1.0, ("MF", "M"): 1.0, ("MF", "AM"): 1.0, ("MF", "D"): 0.75, ("MF", "F"): 0.85,
    ("FW", "F"): 1.0, ("FW", "AM"): 0.9, ("FW", "M"): 0.7, ("FW", "D"): 0.4,
}
OOP_DEFAULT = 0.5
GK_MISMATCH = 0.15        # outfielder in goal, or a keeper outfield

# --- formation presets (rotowire-style slot codes) ---------------------------
FORMATIONS = {
    "4-3-3":   ["GK", "DL", "DC", "DC", "DR", "MC", "MC", "MC", "FWL", "FW", "FWR"],
    "4-2-3-1": ["GK", "DL", "DC", "DC", "DR", "DMC", "DMC", "AML", "AMC", "AMR", "FW"],
    "4-4-2":   ["GK", "DL", "DC", "DC", "DR", "ML", "MC", "MC", "MR", "FW", "FW"],
    "4-1-3-2": ["GK", "DL", "DC", "DC", "DR", "DMC", "MC", "MC", "MC", "FW", "FW"],
    "3-5-2":   ["GK", "DC", "DC", "DC", "ML", "MC", "MC", "MC", "MR", "FW", "FW"],
    "5-3-2":   ["GK", "DL", "DC", "DC", "DC", "DR", "MC", "MC", "MC", "FW", "FW"],
}
