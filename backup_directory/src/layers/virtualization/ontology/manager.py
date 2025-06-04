import json
import logging
import yaml
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, Type
from uuid import UUID, uuid4
from enum import Enum
from src.utils.exceptions import ConfigurationError, InvalidConfigurationError, MissingConfigurationError
from src.utils.config import get_config
logger = logging.getLogger(__name__)

class OntologyFormat(Enum):
    OWL = 'owl'
    RDF = 'rdf'
    JSONLD = 'jsonld'
    TTL = 'ttl'
    N3 = 'n3'
    JSON = 'json'
    YAML = 'yaml'

class TemplateType(Enum):
    DIGITAL_REPLICA = 'digital_replica'
    DIGITAL_TWIN = 'digital_twin'
    SERVICE = 'service'
    DEVICE = 'device'
    PROCESS = 'process'
    CUSTOM = 'custom'

class SemanticProperty:

    def __init__(self, name: str, property_type: str, domain: Optional[str]=None, range_type: Optional[str]=None, description: Optional[str]=None, constraints: Optional[Dict[str, Any]]=None):
        self.name = name
        self.property_type = property_type
        self.domain = domain
        self.range_type = range_type
        self.description = description
        self.constraints = constraints or {}

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'property_type': self.property_type, 'domain': self.domain, 'range_type': self.range_type, 'description': self.description, 'constraints': self.constraints}

class SemanticClass:

    def __init__(self, name: str, uri: str, parent_classes: Optional[List[str]]=None, properties: Optional[List[SemanticProperty]]=None, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None):
        self.name = name
        self.uri = uri
        self.parent_classes = parent_classes or []
        self.properties = properties or []
        self.description = description
        self.metadata = metadata or {}

    def add_property(self, property_obj: SemanticProperty) -> None:
        self.properties.append(property_obj)

    def get_property(self, name: str) -> Optional[SemanticProperty]:
        for prop in self.properties:
            if prop.name == name:
                return prop
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'uri': self.uri, 'parent_classes': self.parent_classes, 'properties': [prop.to_dict() for prop in self.properties], 'description': self.description, 'metadata': self.metadata}

class Ontology:

    def __init__(self, name: str, version: str, namespace: str, format_type: OntologyFormat, source_path: Optional[str]=None):
        self.name = name
        self.version = version
        self.namespace = namespace
        self.format_type = format_type
        self.source_path = source_path
        self.classes: Dict[str, SemanticClass] = {}
        self.properties: Dict[str, SemanticProperty] = {}
        self.loaded_at = datetime.now(timezone.utc)
        self.metadata: Dict[str, Any] = {}

    def add_class(self, semantic_class: SemanticClass) -> None:
        self.classes[semantic_class.name] = semantic_class

    def add_property(self, semantic_property: SemanticProperty) -> None:
        self.properties[semantic_property.name] = semantic_property

    def get_class(self, name: str) -> Optional[SemanticClass]:
        return self.classes.get(name)

    def get_property(self, name: str) -> Optional[SemanticProperty]:
        return self.properties.get(name)

    def validate_instance(self, instance_data: Dict[str, Any], class_name: str) -> List[str]:
        errors = []
        semantic_class = self.get_class(class_name)
        if not semantic_class:
            errors.append(f'Class {class_name} not found in ontology')
            return errors
        for prop in semantic_class.properties:
            if prop.constraints.get('required', False) and prop.name not in instance_data:
                errors.append(f'Required property {prop.name} missing')
        for prop_name, value in instance_data.items():
            prop = semantic_class.get_property(prop_name)
            if prop:
                validation_errors = self._validate_property_value(prop, value)
                errors.extend(validation_errors)
        return errors

    def _validate_property_value(self, prop: SemanticProperty, value: Any) -> List[str]:
        errors = []
        if prop.range_type:
            if not self._check_type_compatibility(value, prop.range_type):
                errors.append(f'Property {prop.name} has invalid type: expected {prop.range_type}')
        for constraint_name, constraint_value in prop.constraints.items():
            if constraint_name == 'min_value' and isinstance(value, (int, float)):
                if value < constraint_value:
                    errors.append(f'Property {prop.name} below minimum value {constraint_value}')
            elif constraint_name == 'max_value' and isinstance(value, (int, float)):
                if value > constraint_value:
                    errors.append(f'Property {prop.name} above maximum value {constraint_value}')
            elif constraint_name == 'pattern' and isinstance(value, str):
                import re
                if not re.match(constraint_value, value):
                    errors.append(f"Property {prop.name} doesn't match pattern {constraint_value}")
        return errors

    def _check_type_compatibility(self, value: Any, expected_type: str) -> bool:
        type_mapping = {'string': str, 'integer': int, 'float': float, 'boolean': bool, 'datetime': str, 'uri': str}
        expected_python_type = type_mapping.get(expected_type.lower())
        if expected_python_type:
            return isinstance(value, expected_python_type)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'version': self.version, 'namespace': self.namespace, 'format_type': self.format_type.value, 'source_path': self.source_path, 'loaded_at': self.loaded_at.isoformat(), 'classes': {name: cls.to_dict() for name, cls in self.classes.items()}, 'properties': {name: prop.to_dict() for name, prop in self.properties.items()}, 'metadata': self.metadata}

class Template:

    def __init__(self, template_id: str, name: str, template_type: TemplateType, version: str, description: str, configuration: Dict[str, Any], ontology_classes: Optional[List[str]]=None, source_path: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None):
        self.template_id = template_id
        self.name = name
        self.template_type = template_type
        self.version = version
        self.description = description
        self.configuration = configuration
        self.ontology_classes = ontology_classes or []
        self.source_path = source_path
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)

    def apply_overrides(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        result = self.configuration.copy()

        def deep_update(base_dict: Dict[str, Any], update_dict: Dict[str, Any]) -> None:
            for key, value in update_dict.items():
                if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                    deep_update(base_dict[key], value)
                else:
                    base_dict[key] = value
        deep_update(result, overrides)
        return result

    def validate_overrides(self, overrides: Dict[str, Any]) -> List[str]:
        errors = []
        allowed_keys = self.metadata.get('allowed_override_keys')
        if allowed_keys:
            for key in overrides.keys():
                if key not in allowed_keys:
                    errors.append(f'Override key {key} not allowed')
        required_keys = self.metadata.get('required_keys', [])
        final_config = self.apply_overrides(overrides)
        for key in required_keys:
            if key not in final_config:
                errors.append(f'Required key {key} missing after overrides')
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {'template_id': self.template_id, 'name': self.name, 'template_type': self.template_type.value, 'version': self.version, 'description': self.description, 'configuration': self.configuration, 'ontology_classes': self.ontology_classes, 'source_path': self.source_path, 'metadata': self.metadata, 'created_at': self.created_at.isoformat()}

class IOntologyLoader(ABC):

    @abstractmethod
    def can_load(self, file_path: Path) -> bool:
        pass

    @abstractmethod
    async def load(self, file_path: Path) -> Ontology:
        pass

class JSONOntologyLoader(IOntologyLoader):

    def can_load(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == '.json'

    async def load(self, file_path: Path) -> Ontology:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ontology = Ontology(name=data.get('name', file_path.stem), version=data.get('version', '1.0.0'), namespace=data.get('namespace', f'urn:{file_path.stem}'), format_type=OntologyFormat.JSON, source_path=str(file_path))
            for class_data in data.get('classes', []):
                properties = []
                for prop_data in class_data.get('properties', []):
                    prop = SemanticProperty(name=prop_data['name'], property_type=prop_data.get('property_type', 'datatype'), domain=prop_data.get('domain'), range_type=prop_data.get('range_type'), description=prop_data.get('description'), constraints=prop_data.get('constraints', {}))
                    properties.append(prop)
                semantic_class = SemanticClass(name=class_data['name'], uri=class_data.get('uri', f"{ontology.namespace}#{class_data['name']}"), parent_classes=class_data.get('parent_classes', []), properties=properties, description=class_data.get('description'), metadata=class_data.get('metadata', {}))
                ontology.add_class(semantic_class)
            for prop_data in data.get('properties', []):
                prop = SemanticProperty(name=prop_data['name'], property_type=prop_data.get('property_type', 'datatype'), domain=prop_data.get('domain'), range_type=prop_data.get('range_type'), description=prop_data.get('description'), constraints=prop_data.get('constraints', {}))
                ontology.add_property(prop)
            ontology.metadata = data.get('metadata', {})
            logger.info(f'Loaded JSON ontology {ontology.name} with {len(ontology.classes)} classes')
            return ontology
        except Exception as e:
            logger.error(f'Failed to load JSON ontology from {file_path}: {e}')
            raise ConfigurationError(f'Failed to load ontology: {e}')

class YAMLOntologyLoader(IOntologyLoader):

    def can_load(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in ['.yaml', '.yml']

    async def load(self, file_path: Path) -> Ontology:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            json_loader = JSONOntologyLoader()
            json_data = {'name': data.get('name', file_path.stem), 'version': data.get('version', '1.0.0'), 'namespace': data.get('namespace', f'urn:{file_path.stem}'), 'classes': data.get('classes', []), 'properties': data.get('properties', []), 'metadata': data.get('metadata', {})}
            ontology = Ontology(name=json_data['name'], version=json_data['version'], namespace=json_data['namespace'], format_type=OntologyFormat.YAML, source_path=str(file_path))
            for class_data in json_data.get('classes', []):
                properties = []
                for prop_data in class_data.get('properties', []):
                    prop = SemanticProperty(name=prop_data['name'], property_type=prop_data.get('property_type', 'datatype'), domain=prop_data.get('domain'), range_type=prop_data.get('range_type'), description=prop_data.get('description'), constraints=prop_data.get('constraints', {}))
                    properties.append(prop)
                semantic_class = SemanticClass(name=class_data['name'], uri=class_data.get('uri', f"{ontology.namespace}#{class_data['name']}"), parent_classes=class_data.get('parent_classes', []), properties=properties, description=class_data.get('description'), metadata=class_data.get('metadata', {}))
                ontology.add_class(semantic_class)
            ontology.metadata = json_data.get('metadata', {})
            logger.info(f'Loaded YAML ontology {ontology.name} with {len(ontology.classes)} classes')
            return ontology
        except Exception as e:
            logger.error(f'Failed to load YAML ontology from {file_path}: {e}')
            raise ConfigurationError(f'Failed to load ontology: {e}')

class OntologyManager:

    def __init__(self, base_path: Optional[Path]=None):
        self.base_path = base_path or Path('templates')
        self.ontologies: Dict[str, Ontology] = {}
        self.templates: Dict[str, Template] = {}
        self.loaders: List[IOntologyLoader] = [JSONOntologyLoader(), YAMLOntologyLoader()]
        self.config = get_config()
        logger.info(f'Initialized OntologyManager with base path: {self.base_path}')

    async def load_ontologies(self, ontology_dir: Optional[Path]=None) -> None:
        search_dir = ontology_dir or self.base_path / 'ontologies'
        if not search_dir.exists():
            logger.warning(f'Ontology directory {search_dir} does not exist')
            return
        logger.info(f'Loading ontologies from {search_dir}')
        for file_path in search_dir.glob('**/*'):
            if file_path.is_file():
                await self._load_ontology_file(file_path)

    async def _load_ontology_file(self, file_path: Path) -> None:
        try:
            loader = None
            for candidate_loader in self.loaders:
                if candidate_loader.can_load(file_path):
                    loader = candidate_loader
                    break
            if not loader:
                logger.debug(f'No loader found for {file_path}')
                return
            ontology = await loader.load(file_path)
            self.ontologies[ontology.name] = ontology
            logger.info(f'Loaded ontology: {ontology.name} v{ontology.version}')
        except Exception as e:
            logger.error(f'Failed to load ontology from {file_path}: {e}')

    async def load_templates(self, template_dir: Optional[Path]=None) -> None:
        search_dir = template_dir or self.base_path / 'digital_replicas'
        if not search_dir.exists():
            logger.warning(f'Template directory {search_dir} does not exist')
            return
        logger.info(f'Loading templates from {search_dir}')
        for file_path in search_dir.glob('**/*.json'):
            await self._load_template_file(file_path)
        for file_path in search_dir.glob('**/*.yaml'):
            await self._load_template_file(file_path)
        for file_path in search_dir.glob('**/*.yml'):
            await self._load_template_file(file_path)

    async def _load_template_file(self, file_path: Path) -> None:
        try:
            if file_path.suffix.lower() == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            template = Template(template_id=data.get('template_id', file_path.stem), name=data.get('name', file_path.stem), template_type=TemplateType(data.get('template_type', 'custom')), version=data.get('version', '1.0.0'), description=data.get('description', ''), configuration=data.get('configuration', {}), ontology_classes=data.get('ontology_classes', []), source_path=str(file_path), metadata=data.get('metadata', {}))
            self.templates[template.template_id] = template
            logger.info(f'Loaded template: {template.name} ({template.template_id})')
        except Exception as e:
            logger.error(f'Failed to load template from {file_path}: {e}')

    def get_ontology(self, name: str) -> Optional[Ontology]:
        return self.ontologies.get(name)

    def get_template(self, template_id: str) -> Optional[Template]:
        return self.templates.get(template_id)

    def list_ontologies(self) -> List[str]:
        return list(self.ontologies.keys())

    def list_templates(self, template_type: Optional[TemplateType]=None) -> List[str]:
        if template_type:
            return [tid for tid, template in self.templates.items() if template.template_type == template_type]
        return list(self.templates.keys())

    def validate_configuration(self, configuration: Dict[str, Any], ontology_name: str, class_name: str) -> List[str]:
        ontology = self.get_ontology(ontology_name)
        if not ontology:
            return [f'Ontology {ontology_name} not found']
        return ontology.validate_instance(configuration, class_name)

    def apply_template(self, template_id: str, overrides: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        template = self.get_template(template_id)
        if not template:
            raise ConfigurationError(f'Template {template_id} not found')
        if overrides:
            validation_errors = template.validate_overrides(overrides)
            if validation_errors:
                raise InvalidConfigurationError(f'Template override validation failed: {validation_errors}')
            return template.apply_overrides(overrides)
        return template.configuration.copy()

    def create_template_from_configuration(self, template_id: str, name: str, configuration: Dict[str, Any], template_type: TemplateType=TemplateType.CUSTOM, description: str='', ontology_classes: Optional[List[str]]=None, metadata: Optional[Dict[str, Any]]=None) -> Template:
        template = Template(template_id=template_id, name=name, template_type=template_type, version='1.0.0', description=description, configuration=configuration, ontology_classes=ontology_classes, metadata=metadata)
        self.templates[template_id] = template
        return template

    def save_template(self, template_id: str, output_path: Optional[Path]=None) -> None:
        template = self.get_template(template_id)
        if not template:
            raise ConfigurationError(f'Template {template_id} not found')
        if output_path is None:
            output_path = self.base_path / 'digital_replicas' / f'{template_id}.json'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(template.to_dict(), f, indent=2, default=str)
        logger.info(f'Saved template {template_id} to {output_path}')

    def register_ontology_loader(self, loader: IOntologyLoader) -> None:
        self.loaders.append(loader)
        logger.info(f'Registered ontology loader: {loader.__class__.__name__}')

    async def reload_all(self) -> None:
        self.ontologies.clear()
        self.templates.clear()
        await self.load_ontologies()
        await self.load_templates()
        logger.info(f'Reloaded {len(self.ontologies)} ontologies and {len(self.templates)} templates')

    def get_statistics(self) -> Dict[str, Any]:
        ontology_stats = {}
        for name, ontology in self.ontologies.items():
            ontology_stats[name] = {'classes': len(ontology.classes), 'properties': len(ontology.properties), 'format': ontology.format_type.value, 'version': ontology.version}
        template_stats = {}
        for template_type in TemplateType:
            template_stats[template_type.value] = len([t for t in self.templates.values() if t.template_type == template_type])
        return {'ontologies': {'count': len(self.ontologies), 'details': ontology_stats}, 'templates': {'count': len(self.templates), 'by_type': template_stats}}
_ontology_manager: Optional[OntologyManager] = None

def get_ontology_manager() -> OntologyManager:
    global _ontology_manager
    if _ontology_manager is None:
        _ontology_manager = OntologyManager()
    return _ontology_manager

async def initialize_ontology_system(base_path: Optional[Path]=None) -> OntologyManager:
    global _ontology_manager
    _ontology_manager = OntologyManager(base_path)
    await _ontology_manager.load_ontologies()
    await _ontology_manager.load_templates()
    return _ontology_manager