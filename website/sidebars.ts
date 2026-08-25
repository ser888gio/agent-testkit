import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// Directory order comes from _category_.json files; pages carry sidebar_position.
const sidebars: SidebarsConfig = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Getting started',
      collapsed: false,
      items: ['getting-started/installation', 'getting-started/quickstart'],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/overview',
        'concepts/test-packs',
        'concepts/sandboxes',
        'concepts/scoring',
        'concepts/redaction',
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/connect-your-agent',
        'guides/choose-a-pack',
        'guides/write-a-test',
        'guides/add-a-sandbox',
        'guides/ci-integration',
        'guides/compliance-evidence',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'reference/cli',
        'reference/target-config',
        'reference/assertions',
        'reference/reports',
      ],
    },
    'limits',
    'troubleshooting',
  ],
};

export default sidebars;
