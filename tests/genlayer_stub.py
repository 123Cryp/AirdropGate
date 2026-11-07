import copy
import types


class u256(int):
    pass


class Address:
    def __init__(self, hex_value):
        self.as_hex = str(hex_value)

    def __eq__(self, other):
        return isinstance(other, Address) and self.as_hex.lower() == other.as_hex.lower()

    def __hash__(self):
        return hash(self.as_hex.lower())

    def __repr__(self):
        return "Address(%s)" % self.as_hex


class TreeMap(dict):
    def __class_getitem__(cls, item):
        return types.GenericAlias(cls, item if isinstance(item, tuple) else (item,))


class DynArray(list):
    def __class_getitem__(cls, item):
        return types.GenericAlias(cls, (item,))


class Return:
    def __init__(self, calldata):
        self.calldata = calldata


class NondetDisagreement(Exception):
    pass


class _Chain:
    def __init__(self):
        self.balances = {}
        self.pages = {}
        self.model = None
        self.model_calls = 0
        self.transfers = []

    def reset(self):
        self.__init__()


chain = _Chain()


class _Message:
    sender_address = Address("0x0000000000000000000000000000000000000000")
    value = u256(0)


class _Handle:
    def __init__(self, addr):
        self.addr = addr

    def emit_transfer(self, value=0, **kwargs):
        if kwargs:
            raise TypeError("emit_transfer to an EOA takes only value")
        key = _Contract.current_address
        if chain.balances.get(key, 0) < int(value):
            raise Exception("insufficient contract balance")
        chain.balances[key] -= int(value)
        chain.transfers.append((self.addr.as_hex, int(value)))


class _Contract:
    current_address = "contract"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        hints = {}
        for klass in reversed(cls.__mro__):
            hints.update(getattr(klass, "__annotations__", {}))
        for name, hint in hints.items():
            origin = getattr(hint, "__origin__", None)
            if origin is TreeMap:
                object.__setattr__(obj, name, TreeMap())
            elif origin is DynArray:
                object.__setattr__(obj, name, DynArray())
            elif hint is u256:
                object.__setattr__(obj, name, u256(0))
        return obj

    @property
    def balance(self):
        return chain.balances.get(_Contract.current_address, 0)


class _Payable:
    def __call__(self, fn):
        fn._payable = True
        return fn


class _Write:
    payable = _Payable()

    def __call__(self, fn):
        return fn


class _Public:
    view = staticmethod(lambda fn: fn)
    write = _Write()


class _Web:
    @staticmethod
    def render(url, mode="text"):
        page = chain.pages.get(url)
        if page is None:
            raise Exception("WEBPAGE_LOAD_FAILED 404")
        return page


class _Nondet:
    web = _Web()

    @staticmethod
    def exec_prompt(prompt, response_format=None):
        chain.model_calls += 1
        if chain.model is None:
            raise Exception("no model configured")
        return chain.model(prompt)


class _Vm:
    Return = Return

    @staticmethod
    def run_nondet_unsafe(leader_fn, validator_fn):
        leader_value = leader_fn()
        if not validator_fn(Return(leader_value)):
            raise NondetDisagreement("validator disagreed with leader")
        return leader_value


class _GL:
    Contract = _Contract
    public = _Public()
    message = _Message()
    nondet = _Nondet()
    vm = _Vm()

    @staticmethod
    def get_contract_at(addr):
        return _Handle(addr)


gl = _GL()

__all__ = ["gl", "Address", "u256", "TreeMap", "DynArray"]


class Harness:
    def __init__(self, cls, deployer, *args):
        chain.reset()
        _Contract.current_address = "contract"
        chain.balances["contract"] = 0
        _GL.message.sender_address = Address(deployer)
        _GL.message.value = u256(0)
        self.contract = cls(*args)

    def call(self, sender, method, *args, value=0):
        snapshot = copy.deepcopy(self.contract.__dict__)
        snap_balance = chain.balances.get("contract", 0)
        snap_transfers = list(chain.transfers)
        _GL.message.sender_address = Address(sender)
        _GL.message.value = u256(value)
        chain.balances["contract"] = snap_balance + value
        try:
            return getattr(self.contract, method)(*args)
        except BaseException:
            self.contract.__dict__.clear()
            self.contract.__dict__.update(snapshot)
            chain.balances["contract"] = snap_balance
            chain.transfers[:] = snap_transfers
            raise
        finally:
            _GL.message.value = u256(0)

    def balance(self):
        return chain.balances.get("contract", 0)
