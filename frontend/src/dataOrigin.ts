/**
 * Data-origin and tier wording. Single place for the UI; the backend has the same strings in
 * app/synthetic.py and a test (tests/test_data_origin.py) compares the two.
 *
 * "Reference test data" is the headline for the generated images (what validation documents call
 * "synthetic"): they are built from published research papers and open-source format
 * documentation, with known ground truth. They are NOT captured from a physical DVR.
 */
export const ORIGIN_LABEL = 'Reference test data'
export const ORIGIN_DEFINITION =
  'built from published research and open-source format documentation, with known ground truth'
export const ORIGIN_DISCLOSURE = 'Not captured from a physical DVR.'
export const ORIGIN_HEADLINE = `${ORIGIN_LABEL}: ${ORIGIN_DEFINITION}`
export const TIER_LIMIT =
  'Tier limit: no vendor is supported above Tier B, and nothing here has been validated on a real device.'
