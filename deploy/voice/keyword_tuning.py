"""Explicit user phonetics; baseline global thresholds remain unchanged."""
import math
from keyword_routes import ALLOWED_KEYWORDS
USER_PHONES='h èi l ū k ǎ @HEY_LUKA'
def candidate_lines(baseline,score=None,threshold=None):
 result=list(baseline)
 phrase=USER_PHONES
 if score is not None or threshold is not None:
  score=1.5 if score is None else score;threshold=.25 if threshold is None else threshold
  if not math.isfinite(score) or not 0<score<=5 or not math.isfinite(threshold) or not 0<threshold<=1:raise ValueError('Invalid keyword parameter')
  phrase=USER_PHONES.replace(' @HEY_LUKA',f' :{score:g} #{threshold:g} @HEY_LUKA')
 if phrase not in result:result.append(phrase)
 return result

def validate_lines(lines,tokens):
 for line in lines:
  fields=line.split()
  if not fields or fields[-1] not in {'@'+x for x in ALLOWED_KEYWORDS}:raise ValueError('Invalid keyword label')
  for field in fields[:-1]:
   if field.startswith((':','#')):
    value=float(field[1:])
    if not math.isfinite(value) or (field[0]==':' and not 0<value<=5) or (field[0]=='#' and not 0<value<=1):raise ValueError('Invalid keyword parameter')
   elif field not in tokens:raise ValueError('Unknown phonetic token')
 return True


def bounded_gain(samples,gain):
 import numpy as np
 if gain not in (1,2,4,8):raise ValueError('Unsupported calibration gain')
 return np.clip(samples.astype(np.float32)*gain,-32768,32767).astype(np.int16)
