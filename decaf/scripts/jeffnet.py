"""jeffnet implements a wrapper over the imagenet classifier trained by Jeff
Donahue using the cuda convnet code.
"""
import cPickle as pickle
from decaf.util import translator
import logging
import numpy as np
import os
from skimage import transform

_JEFFNET_FILE = os.path.join(os.path.dirname(__file__),
                             'imagenet.jeffnet.epoch72')
_META_FILE = os.path.join(os.path.dirname(__file__), 'imagenet.jeffnet.meta')

# This is a legacy flag specifying if the network is trained with vertically
# flipped images, which does not hurt performance but requires us to flip
# the input image first.
_JEFFNET_FLIP = True

# Due to implementational differences between the CPU and GPU codes, our net
# takes in 227x227 images - which supports convolution with 11x11 patches and
# stride 4 to a 55x55 output without any missing pixels. As a note, the GPU
# code takes 224 * 224 images, and does convolution with the same setting and
# no padding. As a result, the last image location is only convolved with 8x8
# image regions.
INPUT_DIM = 227

class JeffNet(object):
    """A wrapper that returns the jeffnet interface to classify images."""
    def __init__(self, net_file=None, meta_file=None):
        """Initializes JeffNet.

        Input:
            net_file: the trained network file.
            meta_file: the meta information for images.
        """
        logging.info('Initializing jeffnet...')
        try:
            if not net_file:
                # use the internal jeffnet file.
                net_file = _JEFFNET_FILE
            if not meta_file:
                # use the internal meta file.
                meta_file = _META_FILE
            cuda_jeffnet = pickle.load(open(net_file))
            meta = pickle.load(open(meta_file))
        except IOError:
            raise RuntimeError('Cannot find JeffNet files.')
        # First, translate the network
        self._net = translator.translate_cuda_network(
            cuda_jeffnet, {'data': (INPUT_DIM, INPUT_DIM, 3)})
        # Then, get the labels and image means.
        self.label_names = meta['label_names']
        self._data_mean = translator.img_cudaconv_to_decaf(
            meta['data_mean'], 256, 3)
        logging.info('Jeffnet initialized.')
        return

    def classify_direct(self, images):
        """Performs the classification directly, assuming that the input
        images are already of the right form.

        Input:
            images: a numpy array of size (num x 227 x 227 x 3), dtype
                float32, c_contiguous, and has the mean subtracted and the
                image flipped if necessary.
        Output:
            scores: a numpy array of size (num x 1000) containing the
                predicted scores for the 1000 classes.
        """
        return self._net.predict(data=images)['probs_cudanet_out']

    @staticmethod
    def oversample(image, center_only=False):
        """Oversamples an image. Currently the indices are hard coded to the
        4 corners and the center of the image, as well as their flipped ones,
        a total of 10 images.

        Input:
            image: an image of size (256 x 256 x 3) and has data type uint8.
            center_only: if True, only return the center image.
        Output:
            images: the output of size (10 x 227 x 227 x 3)
        """
        indices = [0, 256 - INPUT_DIM]
        center = int(indices[1] / 2)
        if center_only:
            return np.ascontiguousarray(
                image[np.newaxis, center:center + INPUT_DIM,
                      center:center + INPUT_DIM], dtype=np.float32)
        else:
            images = np.empty((10, INPUT_DIM, INPUT_DIM, 3),
                              dtype=np.float32)
            curr = 0
            for i in indices:
                for j in indices:
                    images[curr] = image[i:i + INPUT_DIM,
                                         j:j + INPUT_DIM]
                    curr += 1
            images[4] = image[center:center + INPUT_DIM,
                              center:center + INPUT_DIM]
            # flipped version
            images[5:] = images[:5, ::-1]
            return images

    def classify(self, image, center_only=False):
        """Classifies an input image.
        
        Input:
            image: an image of 3 channels and has data type uint8. Only the
                center region will be used for classification.
        Output:
            scores: a numpy vector of size 1000 containing the
                predicted scores for the 1000 classes.
        """
        if image.ndim == 2:
            image = np.tile(image[:, :, np.newaxis], (1, 1, 3))
        elif image.shape[2] == 4:
            # An RGBA image. We will only use the first 3 channels.
            image = image[:, :, :3]
        # Now, reshape the image if necessary
        height, width = image.shape[:2]
        if height < width:
            newshape = (256, int(width * float(256) / height + 0.5))
        else:
            newshape = (int(height * float(256) / width + 0.5), 256)
        image = transform.resize(image, newshape)
        # since skimage transforms the image scale to [0,1), we need to
        # rescale the images.
        image *= 255.
        if _JEFFNET_FLIP:
            # Flip the image if necessary, maintaining the c_contiguous order
            image = image[::-1, :].copy()
        h_offset = (image.shape[0] - 256) / 2
        w_offset = (image.shape[1] - 256) / 2
        image = image[h_offset:h_offset+256, w_offset:w_offset+256]
        # subtract the mean
        image -= self._data_mean
        # oversample the images
        images = JeffNet.oversample(image, center_only)
        predictions = self.classify_direct(images)
        return predictions.mean(0)

    def top_k_prediction(self, scores, k):
        """Returns the top k predictions as well as their names as strings.
        
        Input:
            scores: a numpy vector of size 1000 containing the
                predicted scores for the 1000 classes.
        Output:
            indices: the top k prediction indices.
            names: the top k prediction names.
        """
        indices = scores.argsort()
        return (indices[:-(k+1):-1],
                [self.label_names[i] for i in indices[:-(k+1):-1]])


def main():
    """A simple demo showing how to run jeffnet."""
    from decaf.util import smalldata, visualize
    logging.getLogger().setLevel(logging.INFO)
    net = JeffNet()
    lena = smalldata.lena()
    scores = net.classify(lena)
    print 'prediction:', net.top_k_prediction(scores, 5)
    visualize.draw_net_to_file(net._net, 'jeffnet.png')
    print 'Network structure written to jeffnet.png'


if __name__ == '__main__':
    main()
