from copy import copy
from enum import Enum
from itertools import chain
from typing import Callable

from .Result import Result, Success, Fail
from .util import parse_n, make_gen, str_n, explain_n


class Mode(Enum):
    '''
    贪心匹配 Mode.Greedy
    懒惰匹配 Mode.Lazy
    '''
    Greedy = 'G'
    Lazy = 'L'


class R:
    '''
    正则表达式引擎
    '''

    # --- basic ---
    def __init__(self, target, num=None, name: str = None, mode=Mode.Greedy):
        self.target = target
        self.num_t = parse_n(num)
        self.name = name
        self.mode = mode

        # 逻辑关系单个实例中互斥
        self.and_r = None
        self.or_r = None
        self.invert = False
        self.xor_r = None
        self.next_r = None

        # 状态机
        self.gen = make_gen(target) if not isinstance(target, R) else None

    def __and__(self, other: 'R'):
        this = self.clone()
        this.and_r = other
        return R(this)

    def __or__(self, other: 'R'):
        this = self.clone()
        this.or_r = other
        return R(this)

    def __invert__(self):
        this = self.clone()
        this.invert = True
        return R(this)

    def __xor__(self, other: 'R'):
        this = self.clone()
        this.or_r = other
        return R(this)

    # @在 Python 中表示矩阵乘法, 非常近似于 next
    def __matmul__(self, other: 'R'):
        this = self.clone()
        this.next_r = other
        return R(this)

    def __repr__(self):
        if self.gen and isinstance(self.target, Callable):
            s = '%{}%'.format(self.target.__name__)
        else:
            s = str(self.target)
        s = '({}{})'.format(s, str_n(self.num_t))

        if self.and_r:
            s = '({}&{})'.format(s, self.and_r)
        elif self.or_r:
            s = '({}|{})'.format(s, self.or_r)
        elif self.invert:
            s = '(~{})'.format(s)
        elif self.xor_r:
            s = '({}^{})'.format(s, self.xor_r)

        if self.next_r:
            s += str(self.next_r)
        return s

    def clone(self, **kwargs):
        this = copy(self)
        for k, v in kwargs.items():
            setattr(this, k, v)
        return this

    # --- core ---
    def imatch(self, resource: str, prev_result: Result):
        '''
        接受 2 个参数, 匹配的字符串(resource), 上一个状态机生成的结果(prev_result)
        返回 iter, yield 所有合法结果

        正则匹配可以看成图论, imatch 就像节点用 stream 或者说 pipe 连接
        '''
        # 约定: from_num 和 to_num 在匹配开始时就已经确定
        from_num, to_num = explain_n(prev_result, self.num_t)

        if self.gen:
            # 已递归到最里层
            def stream_num():
                if from_num == 0:
                    # 可选匹配
                    yield prev_result
                if to_num == 0:
                    # 不会匹配到更多
                    return

                counter = 0
                fa = self.gen(prev_result)
                for char in resource[prev_result.ed:]:
                    echo = fa.send(char)

                    if echo == 'GO':
                        continue
                    elif isinstance(echo, Success):
                        counter += 1
                        if from_num <= counter <= to_num:
                            yield echo
                        if counter < to_num:
                            # 未到达边界, 更新 fa
                            fa = self.gen(echo)
                        else:
                            return
                    elif isinstance(echo, Fail):
                        yield echo
                        return

        else:
            def stream_num():
                if from_num == 0:
                    yield prev_result
                if to_num == 0:
                    return

                # DFS
                counter = 1
                curr_iter = (echo for echo in self.target.imatch(resource, prev_result))
                while counter < from_num:
                    counter += 1
                    curr_iter = (echo for echo in
                                 chain.from_iterable(self.target.imatch(resource, i) for i in curr_iter if i))

                q = []

                def tunnel(echo):
                    q.append(echo)
                    return echo

                while counter < to_num:
                    counter += 1
                    curr_iter = (echo for echo in
                                 chain.from_iterable(self.target.imatch(resource, i) for i in curr_iter if i))
                    if counter != to_num:
                        curr_iter = map(tunnel, curr_iter)

                for echo in curr_iter:
                    if q:
                        yield from q
                        q.clear()
                    yield echo

        if self.and_r:
            def stream_logic():
                for echo in stream_num():
                    for and_echo in self.and_r.imatch(resource[prev_result.ed:echo.ed], Result(0, 0)):
                        if and_echo.ed == echo.ed - prev_result.ed and and_echo:
                            yield echo
                            break

        elif self.or_r:
            stream_logic = chain(stream_num(), self.or_r.imatch(resource, prev_result))

        elif self.invert:
            def stream_logic():
                for echo in stream_num():
                    yield echo.invert()

        elif self.xor_r:
            def stream_logic():
                for echo in stream_num():
                    if echo:
                        for xor_echo in self.xor_r.imatch(resource[prev_result.ed:echo.ed], Result(0, 0)):
                            if xor_echo.ed == echo.ed - prev_result.ed and xor_echo:
                                break
                        else:
                            yield echo
                    else:
                        for xor_echo in self.xor_r.imatch(resource, prev_result):
                            if xor_echo:
                                yield xor_echo
        else:
            stream_logic = stream_num

        # 捕获组
        if self.name:
            def stream_name():
                for echo in stream_logic():
                    echo.capture = echo.clone(
                        capture={**echo.capture, self.name: [*echo.capture, (prev_result.ed, echo.ed)]})
        else:
            stream_name = stream_logic

        if self.next_r:
            for echo in stream_name():
                yield from self.next_r.imatch(resource, echo)
        else:
            yield from stream_name()