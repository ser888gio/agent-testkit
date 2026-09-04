import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'agentaudit',
  tagline: 'Black-box testing for AI agents',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://ser888gio.github.io',
  baseUrl: '/agent-testkit/',

  organizationName: 'ser888gio',
  projectName: 'agent-testkit',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Docs are the whole site; no marketing splash to route around.
          routeBasePath: '/',
          editUrl:
            'https://github.com/ser888gio/agent-testkit/tree/develop/docs-web/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'agentaudit',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Docs',
        },
        {
          to: '/getting-started/quickstart',
          label: 'Quickstart',
          position: 'left',
        },
        {
          to: '/reference/cli',
          label: 'Reference',
          position: 'left',
        },
        {
          href: 'https://github.com/ser888gio/agent-testkit',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'What is agentaudit?', to: '/'},
            {label: 'Quickstart', to: '/getting-started/quickstart'},
            {label: 'How it works', to: '/concepts/overview'},
          ],
        },
        {
          title: 'Reference',
          items: [
            {label: 'CLI', to: '/reference/cli'},
            {label: 'Target config', to: '/reference/target-config'},
            {label: 'Assertions', to: '/reference/assertions'},
          ],
        },
        {
          title: 'More',
          items: [
            {label: 'Limits and roadmap', to: '/limits'},
            {label: 'Troubleshooting', to: '/troubleshooting'},
            {
              label: 'GitHub',
              href: 'https://github.com/ser888gio/agent-testkit',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} agentaudit. Apache-2.0. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'python', 'json'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
