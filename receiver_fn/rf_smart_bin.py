#!/usr/bin/env python

import numpy as np
from scipy.spatial.distance import euclidean
from fastdtw import fastdtw
import itertools as iter
from matplotlib.pyplot import plot, show, figure, ylim, xlabel, ylabel,legend,subplot2grid,GridSpec
from copy import deepcopy
from obspy.core.utcdatetime import UTCDateTime

from sklearn.cluster import DBSCAN

# Here are the libraries to deal with RFSTREAM, it uses obspy classes for event and station
#from rf import RFStream
import rf
from obspy.core.event.event import Event
from obspy.core.inventory.station import Station
from joblib import Parallel, delayed
import matplotlib.pyplot as plt

from rf.profile import profile
from tqdm import tqdm
from rf.imaging import plot_profile_map
from rf import get_profile_boxes, iter_event_data, IterMultipleComponents


def compare_pairs(data):
    distance,path=fastdtw(data[0],data[1],dist=euclidean)
    return distance

def crossSpectrum(x, y):

#-------------------Remove mean-------------------
    # nperseg chosen arbitrary based on 126 samples RF signal, experiment to get best results
    nperseg=x.size/20
    cross = np.zeros(nperseg, dtype='complex128')
    for ind in range(x.size / nperseg):

        xp = x[ind * nperseg: (ind + 1)*nperseg]
        yp = y[ind * nperseg: (ind + 1)*nperseg]
        xp = xp - np.mean(xp)
        yp = yp - np.mean(xp)

    # Do FFT
        cfx = np.fft.fft(xp)
        cfy = np.fft.fft(yp)

    # Get cross spectrum
        cross += cfx.conj()*cfy
    freq=np.fft.fftfreq(nperseg)
    return cross,freq

def coh(y,y2):
    # This subroutine determines a coherence level between two signals on normilised frequency
    p11,freq=crossSpectrum(y,y)
    p22,freq=crossSpectrum(y2,y2)
    p12,freq=crossSpectrum(y,y2)
    # coherence
    part1=np.divide(np.abs(p12)**2,p11.real,out=np.zeros_like(np.abs(p12)**2),where=p11.real!=0)
    coh=np.divide(part1,p22.real,out=np.zeros_like(part1),where=p22.real!=0)

#   plot( freq[freq > 0], coh[freq > 0])
#   show()
#   return coh[freq > 0]

    return  freq[freq > 0], coh[freq > 0]

def rf_group_by_similarity(swipe):
    '''
    Module to cluster waveforms by similarity
    swipe - numpy array of RF rowwise
    returns index of the group for each trace. -1 if no group is found for the trace
    '''
    # map is very slow and must be replaced by proper parallelisation
#   distance=map(compare_pairs,iter.combinations(swipe,2))
    distance=Parallel(n_jobs=30,verbose=1)(map(delayed(compare_pairs), iter.combinations(swipe,2)))
    index=list((i,j) for ((i,_),(j,_)) in iter.combinations(enumerate(swipe),2))
#   for i in xrange(len(index)):
#         print index[i],distance[i]
    # First check that distance betwen points
    index=np.array(index)
    distance=np.array(distance)
    matrix=np.zeros((np.amax(index)+1 ,1+np.amax(index)))+np.amax(distance)
#   print matrix[index].shape,distance.shape,index.shape
    matrix[index[:,0],index[:,1]]=distance[:]
    clustering=DBSCAN(eps=3,min_samples=2,metric='precomputed').fit(matrix)

    return clustering.labels_

def coherence(swipe,level,f1,f2):
    ''' Finding coherence between two signals in frequency domain
        swipe - matrix with  waveforms orginised rowwise
        level  - minimum level of coherence (>0.6) for good results
        f1 and f2 - normalised min and max frequencies
        returns array of indexes for coherent traces with median
    '''

    # level - minimum coherence > 0.6 for good results, f2 <0.5 for RF
    median=np.median(swipe,axis=0)

    index=[]
    for i in xrange(swipe.shape[0]):

          f,c=coh(median,swipe[i,:])
          if np.amax(c[f>f1 & f<f2])>level:
             index.append(True)
          else:
             index.append(False)

    return np.array(index)

def knive(swipe,k_level1,sn_level2):
    ind=np.ones((swipe.shape[0],),bool)
    dev=[]
    ch=[]
    knive=[]
    sn=[]
    pulse_ind=np.max(t[t<0])-1.

    for i in xrange(swipe.shape[0]):
        ch.append(np.amax(coh(average,swipe[i,:])))
        dev.append(np.sum((swipe[i,:]-average)**2)/(swipe.shape[0]-1))
        ind[i]=False
        knive.append(np.std(swipe[ind]))
        sn.append(np.std(swipe[i,t>pulse_ind])/np.std(swipe[i,t<pulse_ind]))

    knive=np.array(knive)
    sn=np.array(sn)
    return knive<k_level,sn>sn_level


#-------------Main---------------------------------

if __name__=='__main__':

    ''' @package rf_smart_bin
    This code contains different approaches to select good quality RFs.
    Currently there are three methods
    1. rf_group_by_similarity - grouping method based on calculation of euclidean distances and clustering by similarity ( aca machine learning approach)
    2. coherence - finding the coherent signals (in frequency domain) relative to median. Consequently, moveout should be applied to use this technique
    3. knive - analysing the change of RMS relative to median. Noisy stations will give higher input. Moveout should be applied to use this technique
    '''

    stream=rf.read_rf('rf_pt15_to5Hz.h5','H5')

    # we have to decimate here otherwise clustering method wouldn't perform well. 5Hz sampling
    o_stream=stream.select(component='Q')
    q_stream=o_stream.copy()
    # Filter specified below is only for data analysis and not applied to output data
    q_stream=q_stream.filter('bandpass',freqmin=0.05,freqmax=1.).resample(5)

    # original stream will be resampled to lowest existing sampling rate
    min_sample=10e10
    min_time= UTCDateTime(100*60)

    for trace in o_stream:
        if trace.stats.sampling_rate < min_sample:
            min_sample=trace.stats.sampling_rate

    print "Minimum sampling rate: ",min_sample

    o_stream=o_stream.resample(min_sample).trim2(-5,60,'onset')



    station_list=[]

    # here we collect station names but maybe ID is more appropriate in case of having the same station names in different deployments

    for i in xrange(len(q_stream)):
        station_list.append(q_stream[i].stats.station.encode('utf-8'))

    station_list=np.unique(np.array(station_list))
    print "Gathered ",len(station_list)," stations"

    # here we go with the main loop over stations
    out_file=rf.RFStream()

    for i in xrange(station_list.shape[0]):
        print "Station ",station_list[i],i+1," of ",station_list.shape[0]
        traces=q_stream.select(station=station_list[i])
        # we choose short RF to simplify and speed up the processing
        traces=traces.trim2(-5,20,'onset')

        # but keep original traces as they are to use them at the end
        o_traces=o_stream.select(station=station_list[i])

        swipe=[]
        o_swipe=[]

        for trace in traces:
            swipe.append(trace.data)
        for trace in o_traces:
            o_swipe.append(trace.data)

        swipe=np.array(swipe)
        o_swipe=np.array(o_swipe)

        print "Processing ",swipe.shape[0], " events"
        # we sue clustering technique to find similar signals
        ind=rf_group_by_similarity(swipe)
        num_group=np.amax(ind)

# we have group indexes for each good quality RF trace and apply grouping to original RF traces for stacking

        for k in xrange(num_group+1):
            # average can use weights and mean can work on masked arrays
            stacked=np.average(o_swipe[ind==k,:],axis=0)
            # here we make a trick - coherent signal comes from different directions or segments. Therefore we assign stacked RF back to its original azimuths and angle of incidence
            for j in xrange(len(o_traces)):
                if ind[j]==k:
                    # here we replace original data by stacked rays. However original RFs with assigned groups can be used as well and stacked later using migration image
                    # this option can be more favourable to highlight small signals. Comment out one line below to avoid stacking
                    o_traces[j].data=stacked.copy()
                    out_file.append(o_traces[j])

    ppoints = out_file.ppoints(70)
    boxes = get_profile_boxes((-18.4, 139.1), 135, np.linspace(0, 440, 80), width=500)
    pstream = profile(out_file, boxes)
    pstream.plot_profile(scale=1.5,top='hist')
    plt.show()

    out_file.write('stacked_rf.h5','H5')