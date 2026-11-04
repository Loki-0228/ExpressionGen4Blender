"""Keep texture cards in front of the skin on any target model.

A card is authored in the reference model's head frame, so its depth is the
reference's depth. On another model the face sits somewhere else and the card
ends up behind it: the expression then looks like it does nothing. These
helpers measure that gap and lift the whole card forward.

The card moves as one rigid piece rather than per vertex: pushing each corner
just enough would shear the quad and drag the texture, and a card is a flat
image, not a deformable surface.
"""
import numpy as np

BATCH=256


def _check(card, probes):
    card=np.asarray(card,dtype=float)
    probes=np.asarray(probes,dtype=float)
    if card.size and not np.isfinite(card).all():
        raise ValueError('卡片或表面坐标含无效数值')
    if probes.size and not np.isfinite(probes).all():
        raise ValueError('卡片或表面坐标含无效数值')
    return card,probes


def nearest_probe(card, probes):
    """Nearest surface point per card vertex, measured in the X/Z plane.

    Depth is left out of the search: the skin under a card is decided by where
    it sits on the face, never by how deep it is.
    """
    card,probes=_check(card,probes)
    if not len(card) or not len(probes):return np.zeros_like(card)
    if card.ndim!=2 or probes.ndim!=2:
        raise ValueError('卡片或表面坐标必须是 N×3')
    result=np.empty_like(card)
    flat=probes[:,[0,2]]
    for start in range(0,len(card),BATCH):
        block=card[start:start+BATCH]
        distance=((block[:,None,[0,2]]-flat[None,:,:])**2).sum(axis=2)
        result[start:start+BATCH]=probes[np.argmin(distance,axis=1)]
    return result


def clearance(card, probes):
    """Front gap per vertex: positive means the card is ahead of the skin."""
    card,probes=_check(card,probes)
    if not len(card) or not len(probes):return np.zeros(len(card))
    near=nearest_probe(card,probes)
    return near[:,1]-card[:,1]


def needed_shift(card, probes, margin=.004, scale=1.):
    """Distance to move the whole card along -Y so every vertex clears skin."""
    if not len(np.asarray(card)) or not len(np.asarray(probes)):return 0.
    gap=clearance(card,probes)
    if not len(gap):return 0.
    return max(0.,float(margin)*float(max(scale,0.))-float(gap.min()))


def push_front(card, probes, margin=.004, scale=1.):
    """Return a copy of the card moved forward until it clears the surface."""
    card=np.asarray(card,dtype=float).copy()
    shift=needed_shift(card,probes,margin,scale)
    if shift>0. and card.size:
        card[:,1]-=shift
    return card


def push_behind(card, probes, margin=.004, scale=1.):
    """Return a copy moved back until every vertex sits behind the surface.

    The hidden state has to disappear completely, so it uses the same whole-
    card translation in the opposite direction; a per-vertex fit would bend
    the card out of the head on a curved cheek.
    """
    card=np.asarray(card,dtype=float).copy()
    if not card.size:return card
    gap=clearance(card,probes)
    if not len(gap):return card
    shift=float(max(gap.max(),0.))+float(margin)*float(max(scale,0.))
    if shift>0.:card[:,1]+=shift
    return card
