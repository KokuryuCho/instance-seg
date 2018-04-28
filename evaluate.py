import numpy as np
from torch.autograd import Variable
from scipy.misc import imsave
from scipy.spatial.distance import dice
import hdbscan
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
import matplotlib
#matplotlib.use('Agg')
import matplotlib.pyplot as plt
import skimage.measure
from skimage.transform import rescale
import os
from config import *


def predict_label(features, downsample_factor=1):
    '''
    predicts a segmentation mask from the network output
    :param features: (c,h,w) ndarray containing the feature vectors outputted by the model
    :return: (h,w) ndarray with the predicted label (currently without class predictions
    '''
    features = np.transpose(features, [1,2,0])  # transpose to (h,w,c)
    features = skimage.measure.block_reduce(features, (downsample_factor,downsample_factor,1), np.max) #reduce resolution for performance

    h = features.shape[0]
    w = features.shape[1]
    c = features.shape[2]

    flat_features = np.reshape(features, [h*w,c])
    reduced_features = reduce(flat_features, 10)  # reduce dimension using PCA
    cluster_mask = cluster_features(reduced_features)
    predicted_label = np.reshape(cluster_mask, [h,w])
    predicted_label = rescale(predicted_label, order=0, scale=downsample_factor, preserve_range=True)
    return np.asarray(predicted_label, np.int32)


def cluster_features(features):
    '''
    this function takes a (h*w,c) numpy array, and clusters the c-dim points using MeanShift/DBSCAN.
    this function is meant to use for visualization and evaluation only.
    :param features: (h*w,c) array of h*w d-dim features extracted from the photo.
    :return: returns a (h*w,1) array with the cluster indices.
    '''
    # Define DBSCAN instance and cluster features
    dbscan = hdbscan.HDBSCAN(algorithm='boruvka_kdtree',min_cluster_size=100)
    labels = dbscan.fit_predict(features)
    labels[np.where(labels==-1)] = 0
    # suppress small clusters
    #for i, count in enumerate(counts):
        #if count<100 or instances[i]==-1:
            #labels = np.where(labels==instances[i], 0, labels)

    return labels


def reduce(features, dimension=10):
    '''
    performs PCA dimensionality reduction on the input features
    :param features: a (n, d) or (h,w,d) numpy array containing the data to reduce
    :param dimension: the number of output channels
    :return: a (n, dimension) numpy array containing the reduced data.
    '''
    #features = skimage.measure.block_reduce(features, (downsample,downsample,1), np.max) #reduce resolution for performance
    pca = PCA(n_components=dimension)
    pca_results = pca.fit_transform(features)
    print(np.sum(pca.explained_variance_ratio_))
    return pca_results


def visualize(input, label, features, name, id):
    '''
    This function performs postprocessing (dimensionality reduction and clustering) for a given network
    output. it also visualizes the resulted segmentation along with the original image and the ground truth
    segmentation and saves all the images locally.
    :param input: (3, h, w) ndarray containing rgb data as outputted by the costume datasets
    :param label: (h, w) or (1, h, w) ndarray with the ground truth segmentation
    :param features: (c, h, w) ndarray with the embedded pixels outputted by the network
    :param name: str with the current experiment name
    :param id: an identifier for the current image (for file saving purposes)
    :return: None. all the visualizations are saved locally
    '''
    # Save original image
    os.makedirs('visualizations/' + name+'/segmentations', exist_ok=True)
    img_data = np.transpose(input, [1, 2, 0])
    max_val = np.amax(np.absolute(img_data))
    img_data = (img_data/max_val + 1) / 2  # normalize img
    imsave('visualizations/'+name+'/segmentations/' + str(id) + 'img.jpg', img_data)

    # Save ground truth
    if len(label.shape)==3:
        label = np.squeeze(label)
    label[np.where(label==255)] = 0
    label = label.astype(np.int32)
    imsave('visualizations/'+name+'/segmentations/' + str(id) + 'gt.png', label)

    # reduce features dimensionality and predict label
    predicted_label = predict_label(features, downsample_factor=1)
    imsave('visualizations/'+name+'/segmentations/' + str(id) + 'seg.png', predicted_label)

    return


def best_symmetric_dice(pred, gt):
    score1 = dice_score(pred, gt)
    score2 = dice_score(gt, pred)
    return max([score1, score2])


def dice_score(x, y):
    '''
    computes DICE of a predicted label and ground-truth segmentation. this is done for
    objects with no regard to classes.
    :param x: (1, h, w) or (h, w) ndarray
    :param y: (1, h, w) or (h, w) ndarrayruth segmentation segmentation
    :return: DICE score
    '''

    x_instances = np.unique(x)
    y_instances = np.unique(y)

    total_score = 0

    for x_instance in x_instances:
        max_val = 0
        for y_instance in y_instances:
            x_mask = np.where(x==x_instance, 1, 0)
            y_mask = np.where(y==y_instance, 1, 0)

            overlap = np.sum(np.logical_and(x_mask, y_mask))
            score = 2.0*overlap / np.sum(x_mask+y_mask)

            max_val = max([max_val, score])

        print(max_val)
        total_score += max_val

    return total_score/len(x_instances)


def evaluate_model(model, dataloader, loss_fn):
    '''
    evaluates average loss of a model on a given loss function, and average dice distance of
    some segmentations.
    :param model: the model to use for evaluation
    :param dataloader: a dataloader with the validation set
    :param loss_fn:
    :return: average loss, average dice distance
    '''
    running_loss = 0
    running_dice = 0
    for i, batch in enumerate(dataloader):
        inputs = Variable(batch['image'].type(float_type), volatile=True)
        labels = batch['label'].numpy()

        features = model(inputs)
        current_loss = loss_fn(features, labels)

        np_features = features.data.cpu().numpy()
        pred = predict_label(np_features[0], downsample_factor=2)

        dice_dist = best_symmetric_dice(pred, labels[0])
        running_loss += current_loss.data.numpy()
        running_dice += dice_dist

    val_loss = running_loss / i
    average_dice = running_dice / i

    return val_loss, average_dice