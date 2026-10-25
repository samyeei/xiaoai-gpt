"""Bounded RAM-only speech windows and known-phrase flags; never return transcripts."""
import re
import unicodedata
import numpy as np

def phrase_flags(text):
 text=unicodedata.normalize('NFKC',text).replace('数字','').replace('加上','加')
 text=re.sub(r'<\|.*?\|>','',text)
 text=re.sub(r'[^\w+=]','',text).replace('一','1')
 expression=bool(re.search(r'(?<!\d)1(?:加|\+)1(?!\d)',text))
 question=bool(re.search(r'等于(?:几|多少)|是多少|得几|=(?:几|多少)',text))
 return {'expression_detected':expression,'question_detected':question,'matched_known_test_phrase':expression and question}

def active_windows(channels,rate):
 frame=max(1,round(rate*.02));count=len(channels)//frame
 if not count:return []
 x=channels[:count*frame].reshape(count,frame,-1).astype(np.float32)
 energy=np.sqrt(np.mean(x*x,axis=1)).max(axis=1)
 threshold=max(20.,3.*float(np.percentile(energy,20)))
 active=np.flatnonzero(energy>=threshold)
 if not len(active):return []
 groups=np.split(active,np.flatnonzero(np.diff(active)>61)+1)
 windows=[]
 for group in groups:
  if len(group)<8:continue
  start=max(0,int(group[0]*frame-.4*rate))
  end=min(len(channels),int((group[-1]+1)*frame+.4*rate))
  if end-start>15*rate:continue
  windows.append((start,end))
 return windows[:6]
