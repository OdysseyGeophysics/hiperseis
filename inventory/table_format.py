#!/usr/bin/env python
"""Common format for Pandas Dataframe column ordering of Network, Station and Channel metadata.
"""

import numpy as np
import pandas as pd
from collections import OrderedDict

TABLE_SCHEMA = OrderedDict((
    ('NetworkCode', str),
    ('StationCode', str),
    ('Latitude', np.float64),
    ('Longitude', np.float64),
    ('Elevation', np.float64),
    ('StationStart', np.datetime64),
    ('StationEnd', np.datetime64),
    ('ChannelCode', str),
    ('ChannelStart', np.datetime64),
    ('ChannelEnd', np.datetime64)))

TABLE_COLUMNS = TABLE_SCHEMA.keys()

PANDAS_MAX_TIMESTAMP = str(pd.Timestamp.max)[0:19]