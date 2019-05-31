import codecs
import os
import shutil
import unittest
from tempfile import TemporaryDirectory

import pytest

from mltk.config import (is_config_attribute, Config,
                         ConfigField, BoolValidator, ValidationContext,
                         ConfigValidator, StrValidator, FloatValidator,
                         IntValidator, ConfigValidationError,
                         get_validator, ConfigLoader, FieldValidator)


class ConfigTestCase(unittest.TestCase):

    def test_is_config_attribute(self):
        class SubConfig(Config):
            value = 1
            _private = 2
            field = ConfigField(str)

            class nested(Config):
                value = 123

            nested2 = Config(value=456)

            def get_value(self):
                return self.value

            @property
            def the_value(self):
                return self.value

            @classmethod
            def class_value(cls):
                return cls.value

            @staticmethod
            def static_value():
                return SubConfig.value

        c = SubConfig()
        c.value2 = 2
        for key in ['value', 'field', 'nested', 'nested2']:
            self.assertTrue(is_config_attribute(SubConfig, key))

        for key in ['value', 'value2', 'field', 'nested', 'nested2']:
            self.assertTrue(is_config_attribute(c, key))

        for key in ['value3', '_private', 'get_value', 'the_value',
                    'class_value', 'static_value']:
            self.assertFalse(is_config_attribute(SubConfig, key))
            self.assertFalse(is_config_attribute(c, key))

        for key in ['value3']:
            self.assertTrue(is_config_attribute(
                SubConfig, key, require_existence=False))
            self.assertTrue(is_config_attribute(
                c, key, require_existence=False))

    def test_ConfigField(self):
        # not specifying type and default
        field = ConfigField()
        self.assertEqual(repr(field), 'ConfigField(nullable=True)')

        # specifying default value but not type
        field = ConfigField(default=123)
        self.assertIsNone(field.type)
        self.assertEqual(
            repr(field), 'ConfigField(default=123, nullable=True)')

        # specifying type but not default value
        class MyConfig(Config):
            a = 123

        field = ConfigField(MyConfig)
        self.assertIs(field.type, MyConfig)
        self.assertEqual(
            repr(field),
            'ConfigField(type=ConfigTestCase.test_ConfigField.'
            '<locals>.MyConfig, nullable=True)'
        )

        # specifying the description
        field = ConfigField(int, description='hello')
        self.assertEqual(field.description, 'hello')
        self.assertEqual(
            repr(field), 'ConfigField(type=int, nullable=True)')

        # specifying nullable
        field = ConfigField(nullable=False)
        self.assertFalse(field.nullable)
        self.assertEqual(repr(field), 'ConfigField(nullable=False)')

        # specifying the choices
        field = ConfigField(int, choices=[1, 2, 3])
        self.assertIsInstance(field.choices, tuple)
        self.assertTupleEqual(field.choices, (1, 2, 3))
        self.assertEqual(
            repr(field),
            'ConfigField(type=int, nullable=True, choices=[1, 2, 3])'
        )

    def test_Config_setattr(self):
        config = Config()
        with pytest.raises(TypeError,
                           match='`value` must not be a ConfigField'):
            config.value = ConfigField(int)

        with pytest.raises(AttributeError,
                           match='`name` must not contain \'.\': \'a.b\''):
            setattr(config, 'a.b', 123)

    def test_Config_equality(self):
        class MyConfig(Config):
            value = 123

        equal_samples = [
            (Config(value=123), Config(value=123)),
            (Config(value=Config(value=123)), Config(value=Config(value=123))),
        ]
        inequal_samples = [
            (Config(value=123), Config(value=456)),
            (Config(value=123), Config(value=456, value2=789)),
            (Config(value=Config(value=123)), Config(value=Config(value=456))),
            (Config(value=123), MyConfig()),
        ]

        for a, b in equal_samples:
            self.assertEqual(a, b)
            self.assertEqual(hash(a), hash(b))

        for a, b in inequal_samples:
            self.assertNotEqual(a, b)


class ConfigLoaderTestCase(unittest.TestCase):

    def test_construction(self):
        class MyConfig(Config):
            pass

        loader = ConfigLoader(config_cls=MyConfig)
        self.assertIs(loader.config_cls, MyConfig)
        self.assertFalse(loader.validate_all)

        loader = ConfigLoader(config_cls=MyConfig, validate_all=True)
        self.assertTrue(loader.validate_all)

        with pytest.raises(TypeError,
                           match='`config_cls` is not Config or a subclass of '
                                 'Config: <class \'str\'>'):
            _ = ConfigLoader(str)

    def test_load_object(self):
        class MyConfig(Config):
            class nested1(Config):
                a = 123
                b = ConfigField(float, default=None)

            class nested2(Config):
                c = 789

        # test feed object of invalid type
        loader = ConfigLoader(MyConfig)
        with pytest.raises(TypeError,
                           match='`key_values` must be a dict or a Config '
                                 'object: got \\[1, 2, 3\\]'):
            loader.load_object([1, 2, 3])

        # test load object
        loader.load_object({
            'nested1': Config(a=1230),
            'nested1.b': 456,
            'nested2.c': '7890',
            'nested2': {'d': 'hello'}
        })
        self.assertEqual(
            loader.get(),
            MyConfig(nested1=MyConfig.nested1(a=1230, b=456.0),
                     nested2=MyConfig.nested2(c=7890, d='hello'))
        )

        # test load object error
        with pytest.raises(ValueError,
                           match='at .nested1.a: cannot merge an object '
                                 'attribute into a non-object attribute'):
            loader.load_object({'nested1.a': 123,
                                'nested1': {'a': Config(value=456)}})

    def test_load_object_nested(self):
        class Nested2(Config):
            b = 456

        class Nested3(Config):
            c = 789

        class MyConfig(Config):
            class nested1(Config):
                a = 123

            nested2 = ConfigField(Nested2)
            nested3 = Nested3()

        loader = ConfigLoader(MyConfig)
        loader.load_object({
            'nested1': Config(a=1230),
            'nested2.b': 4560,
            'nested3.c': 7890,
            'nested3': {'d': 'hello'}
        })
        self.assertEqual(
            loader.get(),
            MyConfig(nested1=MyConfig.nested1(a=1230),
                     nested2=Nested2(b=4560.0),
                     nested3=Nested3(c=7890, d='hello'))
        )

    def test_load_file(self):
        with TemporaryDirectory() as temp_dir:
            json_file = os.path.join(temp_dir, 'test.json')
            with codecs.open(json_file, 'wb', 'utf-8') as f:
                f.write('{"a": 1, "nested.b": 2}\n')

            yaml_file = os.path.join(temp_dir, 'test.yaml')
            with codecs.open(yaml_file, 'wb', 'utf-8') as f:
                f.write('a: 1\nnested.b: 2\n')

            expected = Config(a=1, nested=Config(b=2))
            loader = ConfigLoader(Config)

            # test load_json
            loader.load_json(json_file)
            self.assertEqual(loader.get(), expected)

            # test load_yaml
            loader.load_yaml(yaml_file)
            self.assertEqual(loader.get(), expected)

            # test load_file
            loader.load_file(json_file)
            self.assertEqual(loader.get(), expected)
            loader.load_file(yaml_file)
            self.assertEqual(loader.get(), expected)

            yaml_file2 = os.path.join(temp_dir, 'test.YML')
            shutil.copy(yaml_file, yaml_file2)
            loader.load_file(yaml_file2)
            self.assertEqual(loader.get(), expected)

            # test unsupported extension
            txt_file = os.path.join(temp_dir, 'test.txt')
            with codecs.open(txt_file, 'wb', 'utf-8') as f:
                f.write('')

            with pytest.raises(IOError,
                               match='Unsupported config file extension: .txt'):
                _ = loader.load_file(txt_file)

    def test_parse_args(self):
        class MyConfig(Config):
            a = 123
            b = ConfigField(float, default=None)

            class nested(Config):
                c = ConfigField(str, default=None, choices=['hello', 'bye'])
                d = ConfigField(description='anything, but required')

            e = None

        # test help message
        loader = ConfigLoader(MyConfig)
        parser = loader.build_arg_parser()
        self.assertRegex(
            parser.format_help(),
            r"[^@]*"
            r"--a\s+A\s+\(default 123\)\s+"
            r"--b\s+B\s+\(default None\)\s+"
            r"--e\s+E\s+\(default None\)\s+"
            r"--nested\.c\s+NESTED\.C\s+\(default None; choices \['bye', 'hello'\]\)\s+"
            r"--nested\.d\s+NESTED\.D\s+anything, but required\s+\(required\)\s+"
        )

        # test parse
        loader = ConfigLoader(MyConfig)
        loader.parse_args([
            '--nested.c=hello',
            '--nested.d=[1,2,3]',
            '--e={"key":"value"}'  # wrapped by strict dict
        ])
        self.assertEqual(
            loader.get(),
            MyConfig(a=123, b=None, e={'key': 'value'},
                     nested=MyConfig.nested(c='hello', d=[1, 2, 3]))
        )

        # test parse yaml failure, and fallback to str
        loader = ConfigLoader(MyConfig)
        loader.parse_args([
            '--nested.d=[1,2,3',  # not a valid yaml, fallback to str
            '--e={"key":"value"'  # not a valid yaml, fallback to str
        ])
        self.assertEqual(
            loader.get(),
            MyConfig(a=123, b=None, e='{"key":"value"',
                     nested=MyConfig.nested(c=None, d='[1,2,3'))
        )

        # test parse error
        with pytest.raises(ValueError,
                           match=r"at \.nested\.c: value is not one of: "
                                 r"\['hello', 'bye'\]"):
            loader = ConfigLoader(MyConfig)
            loader.parse_args([
                '--nested.c=invalid',
                '--nested.d=True',
            ])
            _ = loader.get()

        with pytest.raises(ValueError,
                           match=r"at \.nested\.d: config attribute is "
                                 r"required but not set"):
            loader = ConfigLoader(MyConfig)
            loader.parse_args([])
            _ = loader.get()

    def test_parse_args_nested(self):
        class Nested2(Config):
            b = 456

        class Nested3(Config):
            c = 789

        class MyConfig(Config):
            class nested1(Config):
                a = 123

            nested2 = ConfigField(Nested2)
            nested3 = Nested3()

        # test help message
        loader = ConfigLoader(MyConfig)
        parser = loader.build_arg_parser()
        self.assertRegex(
            parser.format_help(),
            r"[^@]*"
            r"--nested1\.a\s+NESTED1\.A\s+\(default 123\)\s+"
            r"--nested2\.b\s+NESTED2\.B\s+\(default 456\)\s+"
            r"--nested3\.c\s+NESTED3\.C\s+\(default 789\)\s+"
        )

        # test parse
        loader.parse_args([
            '--nested1.a=1230',
            '--nested2.b=4560',
            '--nested3.c=7890'
        ])
        self.assertEqual(
            loader.get(),
            MyConfig(nested1=MyConfig.nested1(a=1230), nested2=Nested2(b=4560),
                     nested3=Nested3(c=7890))
        )


class ValidatorTestCase(unittest.TestCase):

    def test_ValidationContext(self):
        context = ValidationContext()
        context.get_path()
        with context.enter('.a'):
            assert (context.get_path() == '.a')
            with context.enter('.b'):
                assert (context.get_path() == '.a.b')
            assert (context.get_path() == '.a')
        assert (context.get_path() == '')

    def test_get_validator(self):
        # test validator on empty field
        validator = get_validator(ConfigField())
        self.assertIsInstance(validator, FieldValidator)
        self.assertIsNone(validator.sub_validator)

        # test nested config objects
        class Nested2(Config): pass
        class Nested3(Config): pass
        class MyConfig(Config):
            class nested1(Config): pass

            nested2 = ConfigField(Nested2)
            nested3 = Nested3()

        validator = get_validator(MyConfig.nested1)
        self.assertIsInstance(validator, ConfigValidator)
        self.assertIs(validator.config_cls, MyConfig.nested1)

        validator = get_validator(MyConfig.nested2)
        self.assertIsInstance(validator, FieldValidator)
        self.assertIsInstance(validator.sub_validator, ConfigValidator)
        self.assertIs(validator.sub_validator.config_cls, Nested2)

        validator = get_validator(MyConfig.nested3)
        self.assertIsInstance(validator, ConfigValidator)
        self.assertIs(validator.config_cls, Nested3)

        validator = get_validator(MyConfig().nested1)
        self.assertIsInstance(validator, ConfigValidator)
        self.assertIs(validator.config_cls, MyConfig.nested1)

        validator = get_validator(MyConfig().nested3)
        self.assertIsInstance(validator, ConfigValidator)
        self.assertIs(validator.config_cls, Nested3)

    def test_IntValidator(self):
        v = IntValidator()

        self.assertEqual(v.validate(123), 123)
        self.assertEqual(v.validate(123.), 123)
        self.assertEqual(v.validate('123'), 123)

        with pytest.raises(ConfigValidationError,
                           match='casting a float number into integer is not '
                                 'allowed'):
            _ = v.validate(123.5)

        with pytest.raises(ConfigValidationError,
                           match='invalid literal for int'):
            _ = v.validate('xxx')

        with pytest.raises(ConfigValidationError,
                           match='value is not an integer'):
            _ = v.validate(123., ValidationContext(strict=True))

    def test_FloatValidator(self):
        v = FloatValidator()

        self.assertEqual(v.validate(123), 123.)
        self.assertEqual(v.validate(123.), 123.)
        self.assertEqual(v.validate(123.5), 123.5)
        self.assertEqual(v.validate('123.5'), 123.5)

        with pytest.raises(ConfigValidationError,
                           match='could not convert string to float'):
            _ = v.validate('xxx')

        with pytest.raises(ConfigValidationError,
                           match='value is not a float number'):
            _ = v.validate(123, ValidationContext(strict=True))

    def test_BoolValidator(self):
        v = BoolValidator()

        self.assertEqual(v.validate(True), True)
        self.assertEqual(v.validate('TRUE'), True)
        self.assertEqual(v.validate('On'), True)
        self.assertEqual(v.validate('yes'), True)
        self.assertEqual(v.validate(1), True)

        self.assertEqual(v.validate(False), False)
        self.assertEqual(v.validate('false'), False)
        self.assertEqual(v.validate('OFF'), False)
        self.assertEqual(v.validate('No'), False)
        self.assertEqual(v.validate(0), False)

        with pytest.raises(ConfigValidationError,
                           match='value cannot be casted into boolean'):
            _ = v.validate('xxx')

        with pytest.raises(ConfigValidationError,
                           match='value is not a boolean'):
            _ = v.validate(1, ValidationContext(strict=True))

    def test_StrValidator(self):
        v = StrValidator()

        self.assertEqual(v.validate(''), '')
        self.assertEqual(v.validate('text'), 'text')
        self.assertEqual(v.validate(123), '123')
        self.assertEqual(v.validate(True), 'True')
        self.assertEqual(v.validate(None), 'None')

        with pytest.raises(ConfigValidationError,
                           match='value is not a string'):
            _ = v.validate(1, ValidationContext(strict=True))

    def test_ConfigValidator(self):
        # check construction error
        with pytest.raises(TypeError,
                           match='`config_cls` is not Config class or a '
                                 'sub-class of Config: <class \'str\'>'):
            _ = ConfigValidator(str)

        # check validation error
        class MyConfig(Config):
            a = 123

        validator = ConfigValidator(MyConfig)
        with pytest.raises(ConfigValidationError,
                           match='value is not a ValidatorTestCase.'
                                 'test_ConfigValidator.<locals>.MyConfig'):
            validator.validate(Config(), ValidationContext(strict=True))

        # check validate_all = True
        context = ValidationContext(validate_all=True)
        self.assertEqual(validator.validate('hello', context),
                         'hello')
        with pytest.raises(ConfigValidationError,
                           match='value cannot be casted into '
                                 'ValidatorTestCase.test_ConfigValidator.'
                                 '<locals>.MyConfig'):
            context.throw()

        context = ValidationContext(validate_all=True, strict=True)
        c = Config()
        self.assertIs(validator.validate(c, context), c)
        with pytest.raises(ConfigValidationError,
                           match='value is not a ValidatorTestCase.'
                                 'test_ConfigValidator.<locals>.MyConfig'):
            context.throw()
