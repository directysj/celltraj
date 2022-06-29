import numpy as np
import time, os, sys
from urllib.parse import urlparse
import skimage.io
import matplotlib.pyplot as plt
import subprocess
from skimage import color, morphology
import skimage.transform
from skimage.registration import phase_cross_correlation
from scipy.ndimage import fourier_shift
import h5py
from skimage import transform as tf
from scipy.optimize import minimize
from skimage.segmentation import watershed
from skimage.segmentation import clear_border
from skimage.feature import peak_local_max
import matplotlib.pyplot as plt
from scipy import ndimage
from skimage.filters import threshold_local

def list_images(imagespecifier):
    """list images in a directory matching a pattern..

    :param imagepath: directory :param filespecifier pattern to match for image files
    :type imagepath: string filespecifier string
    :return: list of matching imagefiles
    :rtype: list of strings
    """
    pCommand='ls '+imagespecifier
    p = subprocess.Popen(pCommand, stdout=subprocess.PIPE, shell=True)
    (output, err) = p.communicate()
    output=output.decode()
    fileList=output.split('\n')
    fileList=fileList[0:-1]
    return fileList

def organize_filelist_fov(filelist, fov_pos=None, fov_len=2):
    """Organize imagefiles in a list to field of view.

    :param filelist: list of image files :param fov_pos: string position of fov specifier :param fov_len: length of fov speficier
    :type filelist: list of strings fov_pos: int fov_len: int
    :return: list of imagefiles organized by fov (increasing)
    :rtype: list of strings
    """
    if fov_pos is None:
        print('please input the position of the field of view specifier')
        return
    nF=len(filelist)
    fovlist=np.zeros(nF)
    for i in range(nF):
        fovlist[i]=filelist[i][fov_pos:fov_pos+fov_len]
    indfovs=np.argsort(fovlist)
    fovlist=fovlist[indfovs]
    filelist_sorted=[]
    for i in range(nF):
        filelist_sorted.append(filelist[indfovs[i]])
    return filelist_sorted

def organize_filelist_time(filelist, time_pos=None, time_len=2):
    """Organize imagefiles in a list to timestamp ??d??h??m.

    :param filelist: list of image files :param time_pos: string position of time specifier :param time_len: length of time speficier
    :type filelist: list of strings fov_pos: int fov_len: int
    :return: list of imagefiles organized by fov (increasing)
    :rtype: list of strings
    """
    if time_pos is None:
        print('please input the position of the timestamp specifier')
        return
    nF=len(filelist)
    timelist=np.zeros(nF)
    for i in range(nF):
        timelist[i]=timelist[i][time_pos:time_pos+time_len]
    indtimes=np.argsort(timelist)
    timelist=timelist[indtimes]
    filelist_sorted=[]
    for i in range(nF):
        filelist_sorted.append(filelist[indtimes[i]])
    return filelist_sorted

def znorm(img):
    """Variance normalization (z-norm) of an array or image)..

    :param img: array or image
    :type uuids: real array
    :return: z-normed array
    :rtype: real array
    """
    img=(img-np.mean(img))/np.std(img)
    return img

def histogram_stretch(img,lp=1,hp=99):
    """Histogram stretch of an array or image for normalization..

    :param img: array or image
    :type uuids: real array
    :return: histogram stretched array
    :rtype: real array
    """
    plow, phigh = np.percentile(img, (lp, hp))
    img=(img-plow)/(phigh-plow)
    return img

def get_images(filelist):
    """Get images from list of files.

    :param filelist: list of image files
    :type filelist: list of strings
    :return: list of images
    :rtype: list of arrays
    """
    imgs = [skimage.io.imread(f) for f in filelist]
    return imgs

def get_tile_order(nrows,ncols,snake=False):
    """Construct ordering for to put together image tiles compatible with incell microscope.
    :param nrows: number of rows ncols: number of columns 
    snake: snake across whole image (left to right, right to left, left to right...)
    :type nrows: int ncols: int ncols: int snake: bool
    :return: constructed 2D array of image indices
    :rtype: 2D array (int)
    """
    image_inds=np.flipud(np.arange(nrows*ncols).reshape(nrows,ncols).astype(int))
    if snake:
        for rowv in range(nrows):
            if rowv%2==1:
                image_inds[rowv,:]=np.flip(image_inds[rowv,:])
    return image_inds

def get_slide_image(imgs,nrows=None,ncols=None,foverlap=0.,histnorm=True):
    """Construct slide image from a set of tiles (fields of view). 
    Ordering from (get_tile_order).
    :param imgs: list of images nrows: number of rows, default assumes a square tiling (36 images = 8 rows x 8 cols) 
    ncols: number of columns foverlap: fraction of overlap between images
    :type imgs: list of 2D images (2D arrays) nrows: int ncols: int foverlap: float
    :return: constructed slide image from image tiles
    :rtype: 2D array
    """
    nimg=len(imgs)
    if nrows is None:
        nrows=int(np.sqrt(nimg))
        ncols=nrows
    nh_single=imgs[0].shape[1]
    nv_single=imgs[0].shape[0]
    nfh=int(round(foverlap*nh_single))
    nfv=int(round(foverlap*nv_single))
    npixh=ncols*nh_single-int((ncols-1)*nfh)
    npixv=nrows*nv_single-int((nrows-1)*nfv)
    image_inds=get_tile_order(nrows,ncols)
    ws_img=np.zeros((npixv,npixh)).astype(imgs[0].dtype)
    for im in range(nimg):
        img=imgs[im]
        ih=np.where(image_inds==im)[1][0]
        iv=(nrows-1)-np.where(image_inds==im)[0][0]
        ws_mask=np.ones((npixv,npixh)).astype(int)
        lv=iv*(nv_single-nfv)
        uv=lv+nv_single
        lh=ih*(nh_single-nfh)
        uh=lh+nh_single
        if histnorm:
            img=histogram_stretch(img)
        ws_img[lv:uv,lh:uh]=img
    return ws_img

def load_ilastik(file_ilastik):
    """Load ilastik prediction (pixel classification) from h5 file format.
    :param file_ilastik: filename
    :type file_ilastik: string
    :return: ndarray of ilastik output
    :rtype: 2Dxn array (2D image by n ilastik labels)
    """
    f=h5py.File(file_ilastik,'r')
    dset=f['exported_data']
    pmask=dset[:]
    f.close()
    return pmask

def get_mask_2channel_ilastik(file_ilastik,fore_channel=0,holefill_area=0,pcut=0.8):
    pmask=load_ilastik(file_ilastik)
    msk_fore=pmask[:,:,fore_channel]
    if holefill_area>0:
        msk_fore=skimage.morphology.area_opening(msk_fore, area_threshold=holefill_area)
        msk_fore=skimage.morphology.area_closing(msk_fore, area_threshold=holefill_area)
    msk_fore=msk_fore>pcut
    return msk_fore

def get_masks(masklist,fore_channel=0,holefill_area=0):
    nF=len(masklist)
    masks=[None]*nF
    for iF in range(nF):
        file_ilastik=masklist[iF]
        print('loading '+file_ilastik)
        msk=get_mask_2channel_ilastik(file_ilastik,fore_channel=fore_channel,holefill_area=holefill_area)
        masks[iF]=msk
    return masks

def local_threshold(imgr,imgM=None,pcut=None,histnorm=False,fnuc=0.3,block_size=51):
    nx=np.shape(imgr)[0]
    ny=np.shape(imgr)[1]
    if histnorm:
        imgr=histogram_stretch(imgr)
    if pcut is None:
        if imgM is None:
            pcut=0.8
            print('Using a cutoff of {}. Provide a cutoff value (pcut) or a foreground mask for threshold estimation'.format(pcut))
        else:
            pcut=1.-fnuc*np.sum(imgM)/(nx*ny) #fraction of foreground pixels in nuc sites
    prob_nuc,bins_nuc=np.histogram(imgr.flatten()-np.mean(imgr),100)
    prob_nuc=np.cumsum(prob_nuc/np.sum(prob_nuc))
    nuc_thresh=bins_nuc[np.argmin(np.abs(prob_nuc-pcut))]
    local_thresh = threshold_local(imgr, block_size, offset=-nuc_thresh)
    b_imgr = imgr > local_thresh
    return b_imgr

def get_labeled_mask(b_imgr,imgM=None,apply_watershed=False,fill_holes=True):
    if imgM is None:
        pass
    else:
        indBackground=np.where(np.logical_not(imgM))
        b_imgr[indBackground]=False
    if fill_holes:
        b_imgr=ndimage.binary_fill_holes(b_imgr)
    if apply_watershed:
        d_imgr = ndimage.distance_transform_edt(b_imgr)
        local_maxi = peak_local_max(d_imgr, indices=False, footprint=np.ones((3, 3)), labels=b_imgr)
        #markers_nuc = ndimage.label(local_maxi)[0]
        masks_nuc = watershed(-d_imgr, markers_nuc, mask=b_imgr)
    masks_nuc = ndimage.label(b_imgr)[0]
    return masks_nuc

def clean_labeled_mask(masks_nuc,edge_buffer=5,mincelldim=5,maxcelldim=30,verbose=False):
    minsize=mincelldim*mincelldim
    maxsize=maxcelldim*maxcelldim
    xmin=np.min(np.where(masks_nuc>0)[0]);xmax=np.max(np.where(masks_nuc>0)[0])
    ymin=np.min(np.where(masks_nuc>0)[1]);ymax=np.max(np.where(masks_nuc>0)[1])
    masks_nuc_trimmed=masks_nuc[xmin:xmax,:]; masks_nuc_trimmed=masks_nuc_trimmed[:,ymin:ymax]
    masks_nuc_trimmed=clear_border(masks_nuc_trimmed,buffer_size=edge_buffer)
    bmsk1=np.zeros_like(masks_nuc).astype(bool);bmsk2=np.zeros_like(masks_nuc).astype(bool)
    bmsk1[xmin:xmax,:]=True
    bmsk2[:,ymin:ymax]=True
    indscenter=np.where(np.logical_and(bmsk1,bmsk2))
    masks_nuc_edgeless=np.zeros_like(masks_nuc)
    masks_nuc_edgeless[indscenter]=masks_nuc_trimmed.flatten()
    masks_nuc=masks_nuc_edgeless
    masks_nuc_clean=np.zeros_like(masks_nuc).astype(int)
    nc=1
    for ic in range(1,int(np.max(masks_nuc))+1):
        mskc = masks_nuc==ic
        indc=np.where(mskc)
        npixc=np.sum(mskc)
        if verbose:
	    if npixc<minsize:
		print('cell '+str(ic)+' too small: '+str(npixc))
	    if npixc>maxsize:
		print('cell '+str(ic)+' too big: '+str(npixc))
        if npixc>minsize and npixc<maxsize:
            masks_nuc_clean[indc]=nc
            nc=nc+1
    return masks_nuc_clean

def get_voronoi_masks(labels,imgM=None):
    if imgM is None:
        print('no foreground mask provided (imgM), using entire image')
        imgM=np.ones_like(labels)>0
    indBackground=np.where(np.logical_not(imgM))
    nuc_centers=ndimage.center_of_mass(imgM,labels=labels,index=np.arange(1,np.max(labels)+1).astype(int))
    nuc_centers=np.array(nuc_centers)
    nuc_clusters=pyemma.coordinates.clustering.AssignCenters(nuc_centers, metric='euclidean')
    xx,yy=np.meshgrid(np.arange(nx),np.arange(ny),indexing='ij')
    voronoi_masks=nuc_clusters.assign(np.array([xx.flatten(),yy.flatten()]).T).reshape(nx,ny)+1
    voronoi_masks[indBackground]=0
    masks_cyto=np.zeros_like(voronoi_masks).astype(int)
    for ic in range(1,int(np.max(voronoi_masks))+1):
        mskc = voronoi_masks==ic
        labelsc = ndimage.label(mskc)[0]
        centers=np.array(ndimage.center_of_mass(mskc,labels=labelsc,index=np.arange(1,np.max(labelsc)+1).astype(int)))
        nuc_center=nuc_centers[ic-1]
        dists=np.linalg.norm(centers-nuc_center,axis=1)
        closestCC=np.argmin(dists)+1
        largestCC = np.argmax(np.bincount(labelsc.flat)[1:])+1
        if closestCC != largestCC:
            print('cell: '+str(ic)+' nchunks: '+str(centers.shape[0])+' closest: '+str(closestCC)+' largest: '+str(largestCC))
        largestCC = np.argmax(np.bincount(labelsc.flat)[1:])+1
        indc=np.where(labelsc == closestCC)
        npixc=np.sum(labelsc == closestCC)
        masks_cyto[indc]=ic
    return masks_cyto
