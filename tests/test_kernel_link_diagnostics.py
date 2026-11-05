import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('diagnostics', Path(__file__).resolve().parents[1] / 'scripts/kernel_link_diagnostics.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class DiagnosticsTests(unittest.TestCase):
    def test_missing_source_is_explicit_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = diag.collect(root / 'missing', root / 'evidence')
            self.assertTrue(all('missing' in value for value in report['evidence'].values()))
            self.assertTrue((root / 'evidence/report.json').is_file())

    def test_capture_real_command_and_config_without_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'kernel'
            (source / 'out/init').mkdir(parents=True)
            (source / 'out/.config').write_text('CONFIG_STACKPROTECTOR_PER_TASK=y\nCONFIG_LTO_CLANG_FULL=y\n')
            command = 'cmd_init/main.o := clang -flto -fstack-protector-strong -mstack-protector-guard=sysreg -mstack-protector-guard-reg=sp_el0 -mstack-protector-guard-offset=1234 -c main.c\n'
            (source / 'out/init/.main.o.cmd').write_text(command)
            (source / 'out/init/main.o').write_bytes(b'not evidence')
            (source / 'out/build.log').write_text('LTO vmlinux.o\nld.lld: error: undefined symbol: __stack_chk_guard\n')
            report = diag.collect(source, root / 'evidence')
            flags = report['compile_commands']['out/init/.main.o.cmd']
            self.assertIn('-mstack-protector-guard=sysreg', flags['stack_flags'])
            self.assertEqual(flags['lto_flags'], ['-flto'])
            self.assertIn('__stack_chk_guard', report['errors'][0])
            self.assertEqual((root / 'evidence/out/init/.main.o.cmd').read_text(), command)
            self.assertFalse((root / 'evidence/out/init/main.o').exists())


if __name__ == '__main__':
    unittest.main()
