from .csi1000_predictor import predict_csi1000
from .csi500_predictor import predict_csi500
from .csi300_predictor import predict_csi300
from .chinext_predictor import predict_chinext
from .kc50_predictor import predict_kc50
from .shanghai_predictor import predict_shanghai

__all__ = [
    "predict_csi1000",
    "predict_csi500",
    "predict_csi300",
    "predict_chinext",
    "predict_kc50",
    "predict_shanghai",
]
