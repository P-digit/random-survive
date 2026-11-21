"""여러 모듈이 함께 쓰는 작은 도구."""


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))
