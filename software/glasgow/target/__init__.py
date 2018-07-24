import hashlib
import os
import sys
import tempfile
import shutil
from migen import *

from .platform import GlasgowPlatform
from ..gateware.pads import Pads
from ..gateware.i2c import I2CSlave
from ..gateware.i2c_regs import I2CRegisters
from ..gateware.fx2 import FX2Arbiter


__all__ = ["GlasgowTarget"]


class _CRG(Module):
    def __init__(self, platform):
        clk_if = platform.request("clk_if")

        self.clock_domains.cd_por = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys = ClockDomain()
        self.specials += [
            Instance("SB_GB_IO",
                i_PACKAGE_PIN=clk_if,
                o_GLOBAL_BUFFER_OUTPUT=self.cd_por.clk),
        ]

        reset_delay = Signal(max=2047, reset=2047)
        self.comb += [
            self.cd_sys.clk.eq(self.cd_por.clk),
            self.cd_sys.rst.eq(reset_delay != 0)
        ]
        self.sync.por += [
            If(reset_delay != 0,
                reset_delay.eq(reset_delay - 1)
            )
        ]


class GlasgowTarget(Module):
    sys_clk_freq = 30e6

    def __init__(self, multiplexer_cls=None):
        self.platform = GlasgowPlatform()

        self.submodules.crg = _CRG(self.platform)

        self.submodules.i2c_pads  = Pads(self.platform.request("i2c"))
        self.submodules.i2c_slave = I2CSlave(self.i2c_pads)
        self.submodules.registers = I2CRegisters(self.i2c_slave)
        self.comb += self.i2c_slave.address.eq(0b0001000)

        self.submodules.fx2_arbiter = FX2Arbiter(self.platform.request("fx2"))

        if multiplexer_cls:
            self.submodules.multiplexer = multiplexer_cls(ports={
                "A": lambda: self.platform.request("io"),
                "B": lambda: self.platform.request("io"),
                "S": lambda: self.platform.request("sync")
            }, fifo_count=2, fx2_arbiter=self.fx2_arbiter)

    def get_fragment(self):
        # TODO: shouldn't this be done in migen?
        if self.get_fragment_called:
            return self._fragment
        return super().get_fragment()

    def build(self, **kwargs):
        self.platform.build(self, **kwargs)

    def get_verilog(self, **kwargs):
        return self.platform.get_verilog(self)

    def get_bitstream_id(self, **kwargs):
        verilog = str(self.get_verilog(**kwargs))
        return hashlib.sha256(verilog.encode("utf-8")).digest()[:16]

    def get_bitstream(self, build_dir=None, debug=False, **kwargs):
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            self.build(build_dir=build_dir)
            with open(os.path.join(build_dir, "top.bin"), "rb") as f:
                bitstream = f.read()
            if debug:
                shutil.rmtree(build_dir)
        except:
            if debug:
                print("Keeping build tree as " + build_dir, file=sys.stderr)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)
        return bitstream