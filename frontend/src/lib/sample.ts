/**
 * Example data for the "Try an example" flow — a real source article and two
 * outputs (a faithful human summary and a flawed LLM summary) that exercise
 * the whole pipeline: a wrong number, a contradiction, a dropped fact, and
 * introduced bias.
 */

import type { OutputInput, SourceInput } from '@/api/auditor-types';

export const SAMPLE_SOURCE: SourceInput = {
  text: `Northwind Energy reported revenue of $5.2 billion in 2023, up 8 percent from 2022. The company said operating margins improved this year on lower fuel costs. Northwind employs 12,000 people across four countries. The board approved a special dividend of $0.40 per share, payable in March. The CEO cautioned that regulatory changes could pressure earnings in 2024.`,
};

export const SAMPLE_OUTPUTS: OutputInput[] = [
  {
    producer: 'human',
    output_type: 'summary',
    text: `Northwind Energy's 2023 revenue was $5.2 billion, up 8% from 2022, with improved operating margins on lower fuel costs. The company employs 12,000 people in four countries and approved a $0.40 special dividend payable in March. The CEO warned that 2024 regulatory changes could pressure earnings.`,
  },
  {
    producer: 'llm',
    output_type: 'summary',
    text: `Northwind Energy posted a stunning $6.1 billion in revenue in 2023, and operating margins declined sharply. The company employs 12,000 people. Analysts expect a disastrous 2024 as regulation tightens.`,
  },
];
